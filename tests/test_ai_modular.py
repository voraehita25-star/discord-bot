"""
Tests for AI Core Modular Components
Comprehensive tests for performance, message_queue, context_builder, and response_sender modules.
Target: 80%+ coverage for these new modules.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

# ============================================================================
# Performance Module Tests
# ============================================================================


class TestPerformanceTracker:
    """Tests for PerformanceTracker class."""

    def test_init(self):
        """Test PerformanceTracker initialization."""
        from cogs.ai_core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        assert tracker._metrics is not None
        assert "api_call" in tracker._metrics

    def test_record_timing(self):
        """Test recording timing for a step."""
        from cogs.ai_core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.5)

        assert "api_call" in tracker._metrics
        assert len(tracker._metrics["api_call"]) == 1
        assert tracker._metrics["api_call"][0] == 0.5

    def test_record_multiple_timings(self):
        """Test recording multiple timings for same step."""
        from cogs.ai_core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        for i in range(5):
            tracker.record_timing("api_call", 0.1 * (i + 1))

        assert len(tracker._metrics["api_call"]) == 5

    def test_max_samples_limit(self):
        """Test that max_samples limit is enforced."""
        from cogs.ai_core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        # Record more than PERFORMANCE_SAMPLES_MAX (100)
        for i in range(150):
            tracker.record_timing("test_step", float(i))

        # Should only keep last 100 samples (PERFORMANCE_SAMPLES_MAX)
        assert len(tracker._metrics["test_step"]) == 100

    def test_get_stats_empty(self):
        """Test get_stats with only initialized steps (no data added)."""
        from cogs.ai_core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        stats = tracker.get_stats()
        # Default steps exist but have no data
        assert "api_call" in stats
        assert stats["api_call"]["count"] == 0

    def test_get_stats_with_data(self):
        """Test get_stats with recorded data."""
        from cogs.ai_core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.1)
        tracker.record_timing("api_call", 0.3)
        tracker.record_timing("api_call", 0.2)

        stats = tracker.get_stats()
        assert "api_call" in stats
        assert stats["api_call"]["count"] == 3
        assert stats["api_call"]["avg_ms"] == 200.0  # 0.2s average = 200ms
        assert stats["api_call"]["min_ms"] == 100.0
        assert stats["api_call"]["max_ms"] == 300.0

    def test_get_stats_single_step(self):
        """Test get_step_stats for a single step."""
        from cogs.ai_core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("rag_search", 0.05)
        tracker.record_timing("streaming", 0.15)

        stats = tracker.get_step_stats("rag_search")
        assert stats["count"] == 1
        assert stats["avg_ms"] == 50.0

    def test_clear_metrics(self):
        """Test clearing metrics."""
        from cogs.ai_core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.5)
        tracker.clear_metrics()

        assert tracker._metrics["api_call"] == []

    def test_clear_single_step(self):
        """Test clearing a single step."""
        from cogs.ai_core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.5)
        tracker.record_timing("rag_search", 0.1)
        tracker.clear_metrics("api_call")

        assert tracker._metrics["api_call"] == []
        assert len(tracker._metrics["rag_search"]) == 1

    def test_get_summary(self):
        """Test getting performance summary."""
        from cogs.ai_core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.5)

        summary = tracker.get_summary()
        assert "📊 Performance Summary:" in summary
        assert "api_call" in summary


class TestRequestDeduplicator:
    """Tests for RequestDeduplicator class."""

    def test_init(self):
        """Test RequestDeduplicator initialization."""
        from cogs.ai_core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        assert dedup._pending_requests == {}

    def test_is_duplicate_new_request(self):
        """Test that new request is not duplicate."""
        from cogs.ai_core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        is_dup = dedup.is_duplicate("key1")

        assert is_dup is False  # Not in pending yet

        # Add it
        dedup.add_request("key1")
        assert "key1" in dedup._pending_requests

    def test_is_duplicate_existing_request(self):
        """Test that existing request is duplicate."""
        from cogs.ai_core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        dedup.add_request("key1")  # First add
        is_dup = dedup.is_duplicate("key1")  # Now check

        assert is_dup is True

    def test_remove_request(self):
        """Test removing a request."""
        from cogs.ai_core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        dedup.add_request("key1")
        dedup.remove_request("key1")

        assert "key1" not in dedup._pending_requests

    def test_cleanup_old_requests(self):
        """Test cleanup of old requests."""
        from cogs.ai_core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        # Add a request with old timestamp
        dedup._pending_requests["old_key"] = time.time() - 120  # 2 minutes ago
        dedup._pending_requests["new_key"] = time.time()

        cleaned = dedup.cleanup(max_age=60.0)

        assert cleaned == 1
        assert "old_key" not in dedup._pending_requests
        assert "new_key" in dedup._pending_requests

    def test_generate_key(self):
        """Test key generation."""
        from cogs.ai_core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        key = dedup.generate_key(123, 456, "test message")

        assert "123" in key
        assert "456" in key

    def test_get_pending_count(self):
        """Test getting pending count."""
        from cogs.ai_core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        assert dedup.get_pending_count() == 0

        dedup.add_request("key1")
        dedup.add_request("key2")
        assert dedup.get_pending_count() == 2


# ============================================================================
# Message Queue Module Tests
# ============================================================================


class TestPendingMessage:
    """Tests for PendingMessage dataclass."""

    def test_create_pending_message(self):
        """Test creating a PendingMessage."""
        from cogs.ai_core.message_queue import PendingMessage

        channel = MagicMock()
        user = MagicMock()

        msg = PendingMessage(
            channel=channel,
            user=user,
            message="Hello",
        )

        assert msg.channel == channel
        assert msg.user == user
        assert msg.message == "Hello"
        assert msg.attachments is None
        assert msg.output_channel is None
        assert msg.generate_response is True

    def test_pending_message_with_all_fields(self):
        """Test PendingMessage with all fields."""
        from cogs.ai_core.message_queue import PendingMessage

        channel = MagicMock()
        user = MagicMock()
        output = MagicMock()
        attachments = [MagicMock()]

        msg = PendingMessage(
            channel=channel,
            user=user,
            message="Test",
            attachments=attachments,
            output_channel=output,
            generate_response=False,
            user_message_id=12345,
        )

        assert msg.attachments == attachments
        assert msg.output_channel == output
        assert msg.generate_response is False
        assert msg.user_message_id == 12345


class TestMessageQueue:
    """Tests for MessageQueue class."""

    def test_init(self):
        """Test MessageQueue initialization."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        assert queue.pending_messages == {}
        assert queue.cancel_flags == {}
        assert queue.processing_locks == {}

    def test_get_lock(self):
        """Test getting a lock for a channel."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        lock = queue.get_lock_sync(123)

        assert isinstance(lock, asyncio.Lock)
        assert 123 in queue.processing_locks

    def test_get_lock_same_channel(self):
        """Test getting same lock for same channel."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        lock1 = queue.get_lock_sync(123)
        lock2 = queue.get_lock_sync(123)

        assert lock1 is lock2

    def test_queue_message(self):
        """Test queuing a message."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        channel = MagicMock()
        user = MagicMock()

        queue.queue_message(
            channel_id=123,
            channel=channel,
            user=user,
            message="Hello",
        )

        assert 123 in queue.pending_messages
        assert len(queue.pending_messages[123]) == 1

    def test_signal_cancel(self):
        """Test signaling cancel for a channel."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        queue.signal_cancel(123)

        assert queue.cancel_flags[123] is True

    def test_reset_cancel(self):
        """Test resetting cancel flag."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        queue.signal_cancel(123)
        queue.reset_cancel(123)

        assert queue.cancel_flags[123] is False

    def test_is_cancelled(self):
        """Test checking if cancelled."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        assert queue.is_cancelled(123) is False

        queue.signal_cancel(123)
        assert queue.is_cancelled(123) is True

    def test_has_pending(self):
        """Test checking for pending messages."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        assert queue.has_pending(123) is False

        queue.queue_message(123, MagicMock(), MagicMock(), "Test")
        assert queue.has_pending(123) is True

    def test_get_pending_count(self):
        """Test getting pending message count."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        assert queue.get_pending_count(123) == 0

        queue.queue_message(123, MagicMock(), MagicMock(), "Test1")
        queue.queue_message(123, MagicMock(), MagicMock(), "Test2")
        assert queue.get_pending_count(123) == 2

    def test_pop_pending_messages(self):
        """Test popping pending messages."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        queue.queue_message(123, MagicMock(), MagicMock(), "Test1")
        queue.queue_message(123, MagicMock(), MagicMock(), "Test2")
        queue.signal_cancel(123)

        messages = queue.pop_pending_messages(123)

        assert len(messages) == 2
        assert queue.pending_messages[123] == []
        assert queue.cancel_flags[123] is False

    def test_merge_pending_messages(self):
        """Test merging pending messages."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()

        user1 = MagicMock()
        user1.display_name = "User1"
        user2 = MagicMock()
        user2.display_name = "User2"

        queue.queue_message(123, MagicMock(), user1, "Hello")
        queue.queue_message(123, MagicMock(), user2, "World")

        latest, combined = queue.merge_pending_messages(123)

        assert latest is not None
        assert "[User1]: Hello" in combined
        assert "[User2]: World" in combined

    def test_merge_single_message(self):
        """Test merging single message returns original."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        user = MagicMock()
        user.display_name = "User"

        queue.queue_message(123, MagicMock(), user, "Hello")

        latest, combined = queue.merge_pending_messages(123)

        assert combined == "Hello"

    def test_merge_empty_queue(self):
        """Test merging empty queue."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()

        latest, combined = queue.merge_pending_messages(123)

        assert latest is None
        assert combined == ""

    @pytest.mark.asyncio
    async def test_acquire_lock_with_timeout(self):
        """Test acquiring lock with timeout."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        result = await queue.acquire_lock_with_timeout(123, timeout=5.0)

        assert result is True
        assert queue.is_locked(123) is True

        # Release for cleanup
        queue.release_lock(123)

    @pytest.mark.asyncio
    async def test_acquire_lock_timeout(self):
        """Test lock acquisition timeout."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        lock = queue.get_lock_sync(123)
        await lock.acquire()  # Lock it first

        # Try to acquire again - should timeout
        result = await queue.acquire_lock_with_timeout(123, timeout=0.1)

        assert result is False

        # Cleanup
        lock.release()

    def test_release_lock(self):
        """Test releasing a lock."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        _ = queue.get_lock_sync(123)  # Lock created for side effect

        # Acquire then release
        asyncio.new_event_loop().run_until_complete(
            queue.acquire_lock_with_timeout(123)
        )
        queue.release_lock(123)

        assert queue.is_locked(123) is False

    def test_cleanup_stale_locks(self):
        """Test detecting stale locks (no longer force-releases)."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()
        # Add old lock time
        queue._lock_times[123] = time.time() - 400  # 400 seconds ago
        queue.get_lock_sync(123)

        # cleanup_stale_locks now only detects stale locks (doesn't release)
        stale_count = queue.cleanup_stale_locks(max_age=300.0)

        # Should detect 1 stale lock
        assert stale_count == 1
        # Lock time should still be present (not released)
        assert 123 in queue._lock_times


# ============================================================================
# Context Builder Module Tests
# ============================================================================


class TestAIContext:
    """Tests for AIContext dataclass."""

    def test_create_context(self):
        """Test creating AIContext."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext()

        assert ctx.avatar_name is None
        assert ctx.rag_context == ""
        assert ctx.entity_memory == ""

    def test_has_avatar(self):
        """Test has_avatar property."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext()
        assert ctx.has_avatar is False

        ctx.avatar_name = "Faust"
        assert ctx.has_avatar is True

    def test_build_system_context_empty(self):
        """Test building empty system context."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext()
        result = ctx.build_system_context()

        assert result == ""

    def test_build_system_context_full(self):
        """Test building full system context."""
        from cogs.ai_core.context_builder import AIContext

        ctx = AIContext(
            instructions="Be helpful",
            rag_context="Related: ABC",
            entity_memory="User: likes cats",
            state_tracker="Current state: idle",
            url_content="https://example.com: Some content",
        )

        result = ctx.build_system_context()

        assert "## Instructions" in result
        assert "Be helpful" in result
        assert "## Relevant Knowledge" in result
        assert "## Entity Memory" in result
        assert "## State Tracker" in result
        assert "## URL Content" in result


class TestContextBuilder:
    """Tests for ContextBuilder class."""

    def test_init(self):
        """Test ContextBuilder initialization."""
        from cogs.ai_core.context_builder import ContextBuilder

        builder = ContextBuilder()

        assert builder.memory_manager is None
        assert builder.entity_memory is None

    def test_init_with_components(self):
        """Test ContextBuilder with components."""
        from cogs.ai_core.context_builder import ContextBuilder

        memory = MagicMock()
        entity = MagicMock()

        builder = ContextBuilder(
            memory_manager=memory,
            entity_memory=entity,
        )

        assert builder.memory_manager == memory
        assert builder.entity_memory == entity

    @pytest.mark.asyncio
    async def test_build_context_empty(self):
        """Test building context with no components."""
        from cogs.ai_core.context_builder import ContextBuilder

        builder = ContextBuilder()
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Hello",
        )

        assert ctx.rag_context == ""
        assert ctx.entity_memory == ""

    @pytest.mark.asyncio
    async def test_build_context_with_rag(self):
        """Test building context with RAG."""
        from cogs.ai_core.context_builder import ContextBuilder

        memory_manager = MagicMock()
        memory_manager.semantic_search = AsyncMock(return_value=[
            {"text": "Memory 1", "score": 0.9},
            {"text": "Memory 2", "score": 0.8},
        ])

        builder = ContextBuilder(memory_manager=memory_manager)
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="What did we discuss?",
        )

        assert "Memory 1" in ctx.rag_context
        assert "Memory 2" in ctx.rag_context

    @pytest.mark.asyncio
    async def test_build_context_with_avatar(self):
        """Test building context with avatar."""
        from cogs.ai_core.context_builder import ContextBuilder

        avatar_manager = MagicMock()
        avatar_manager.get_avatar = AsyncMock(return_value={
            "name": "Faust",
            "personality": "Mischievous",
            "image_url": "https://example.com/faust.png",
        })

        guild = MagicMock()

        builder = ContextBuilder(avatar_manager=avatar_manager)
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Hello",
            guild=guild,
        )

        assert ctx.avatar_name == "Faust"
        assert ctx.avatar_personality == "Mischievous"

    @pytest.mark.asyncio
    async def test_get_rag_context_no_results(self):
        """Test RAG context with no results."""
        from cogs.ai_core.context_builder import ContextBuilder

        memory_manager = MagicMock()
        memory_manager.semantic_search = AsyncMock(return_value=[])

        builder = ContextBuilder(memory_manager=memory_manager)
        result = await builder._get_rag_context(123, "query")

        assert result == ""

    @pytest.mark.asyncio
    async def test_get_rag_context_fallback_search(self):
        """Test RAG context with fallback search method."""
        from cogs.ai_core.context_builder import ContextBuilder

        memory_manager = MagicMock(spec=["search"])
        memory_manager.search = AsyncMock(return_value=[
            {"content": "Result 1"},
        ])

        builder = ContextBuilder(memory_manager=memory_manager)
        result = await builder._get_rag_context(123, "query")

        assert "Result 1" in result

    @pytest.mark.asyncio
    async def test_get_entity_memory(self):
        """Test getting entity memory."""
        from cogs.ai_core.context_builder import ContextBuilder

        entity_memory = MagicMock()
        entity_memory.get_relevant = AsyncMock(return_value=[
            {"name": "Alice", "info": "Likes coding"},
        ])

        builder = ContextBuilder(entity_memory=entity_memory)
        result = await builder._get_entity_memory(123, 456, "message")

        assert "Alice" in result
        assert "Likes coding" in result

    @pytest.mark.asyncio
    async def test_get_state_tracker(self):
        """Test getting state tracker."""
        from cogs.ai_core.context_builder import ContextBuilder

        state_tracker = MagicMock()
        state_tracker.get_state_summary = AsyncMock(return_value="Current state: active")

        builder = ContextBuilder(state_tracker=state_tracker)
        result = await builder._get_state_tracker(123)

        assert result == "Current state: active"

    @pytest.mark.asyncio
    async def test_build_context_handles_exceptions(self):
        """Test that build_context handles exceptions gracefully."""
        from cogs.ai_core.context_builder import ContextBuilder

        memory_manager = MagicMock()
        memory_manager.semantic_search = AsyncMock(side_effect=Exception("Test error"))

        builder = ContextBuilder(memory_manager=memory_manager)
        # Should not raise, should return empty context
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Hello",
        )

        assert ctx.rag_context == ""


# ============================================================================
# Response Sender Module Tests
# ============================================================================


class TestSendResult:
    """Tests for SendResult dataclass."""

    def test_create_success_result(self):
        """Test creating success result."""
        from cogs.ai_core.response_sender import SendResult

        result = SendResult(success=True, message_id=12345)

        assert result.success is True
        assert result.message_id == 12345
        assert result.error is None

    def test_create_error_result(self):
        """Test creating error result."""
        from cogs.ai_core.response_sender import SendResult

        result = SendResult(success=False, error="Failed to send")

        assert result.success is False
        assert result.error == "Failed to send"


class TestResponseSender:
    """Tests for ResponseSender class."""

    def test_init(self):
        """Test ResponseSender initialization."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        assert sender.webhook_cache is None
        assert sender.avatar_manager is None

    def test_extract_character_tag(self):
        """Test extracting character tag."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        name, content = sender.extract_character_tag("[Alice]: Hello!")

        assert name == "Alice"
        assert content == "Hello!"

    def test_extract_character_tag_none(self):
        """Test extracting when no tag present."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        name, content = sender.extract_character_tag("Hello world!")

        assert name is None
        assert content == "Hello world!"

    def test_split_content_short(self):
        """Test splitting short content."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        chunks = sender.split_content("Hello")

        assert len(chunks) == 1
        assert chunks[0] == "Hello"

    def test_split_content_long(self):
        """Test splitting long content."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        # Create content longer than 2000 chars
        long_content = "A" * 2500
        chunks = sender.split_content(long_content, max_length=1000)

        assert len(chunks) == 3
        for chunk in chunks:
            assert len(chunk) <= 1000

    def test_split_content_at_paragraph(self):
        """Test splitting at paragraph break."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        content = "First paragraph.\n\n" + "A" * 1900
        chunks = sender.split_content(content, max_length=2000)

        assert len(chunks) >= 1

    def test_split_content_at_sentence(self):
        """Test splitting at sentence break."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        content = "First sentence. " + "A" * 1990
        chunks = sender.split_content(content, max_length=2000)

        # First chunk should end at sentence
        assert chunks[0].endswith(". ") or len(chunks[0]) <= 2000

    def test_sanitize_content(self):
        """Test sanitizing content."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        content = "Hello\x00World\n\n\nTest"
        result = sender.sanitize_content(content)

        assert "\x00" not in result
        assert "\n\n\n" not in result

    def test_sanitize_empty_content(self):
        """Test sanitizing empty content."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        result = sender.sanitize_content("")
        assert result == ""

        result = sender.sanitize_content(None)
        assert result == ""

    @pytest.mark.asyncio
    async def test_send_response_empty(self):
        """Test sending empty response."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()
        channel = MagicMock()

        result = await sender.send_response(channel, "")

        assert result.success is False
        assert "Empty" in result.error

    @pytest.mark.asyncio
    async def test_send_response_direct(self):
        """Test sending response directly."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        sent_msg = MagicMock()
        sent_msg.id = 12345

        channel = MagicMock()
        channel.send = AsyncMock(return_value=sent_msg)

        result = await sender.send_response(
            channel,
            "Hello world!",
            use_webhook=False,
        )

        assert result.success is True
        assert result.message_id == 12345
        assert result.sent_via == "direct"

    @pytest.mark.asyncio
    async def test_send_response_chunked(self):
        """Test sending chunked response."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        sent_msg = MagicMock()
        sent_msg.id = 12345

        channel = MagicMock()
        channel.send = AsyncMock(return_value=sent_msg)

        # Send long content that needs chunking
        long_content = "A" * 3000
        result = await sender.send_response(
            channel,
            long_content,
            use_webhook=False,
        )

        assert result.success is True
        assert result.chunk_count > 1
        assert result.sent_via == "chunked"

    @pytest.mark.asyncio
    async def test_send_response_with_character_tag(self):
        """Test sending response with character tag."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        sent_msg = MagicMock()
        sent_msg.id = 12345

        channel = MagicMock()
        channel.send = AsyncMock(return_value=sent_msg)

        result = await sender.send_response(
            channel,
            "[Faust]: Hello!",
            use_webhook=False,
        )

        assert result.success is True
        # Content should have tag extracted
        channel.send.assert_called()

    @pytest.mark.asyncio
    async def test_edit_message(self):
        """Test editing a message."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        message = MagicMock()
        message.edit = AsyncMock()

        result = await sender.edit_message(message, "New content")

        assert result is True
        message.edit.assert_called_once_with(content="New content")

    @pytest.mark.asyncio
    async def test_edit_message_truncate(self):
        """Test editing message with truncation."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        message = MagicMock()
        message.edit = AsyncMock()

        long_content = "A" * 3000
        result = await sender.edit_message(message, long_content)

        assert result is True
        # Should truncate
        call_args = message.edit.call_args
        assert len(call_args[1]["content"]) <= 2000

    @pytest.mark.asyncio
    async def test_edit_message_error(self):
        """Test editing message with error."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        message = MagicMock()
        message.edit = AsyncMock(side_effect=Exception("Edit failed"))

        result = await sender.edit_message(message, "Content")

        assert result is False

    @pytest.mark.asyncio
    async def test_send_typing(self):
        """Test sending typing indicator."""
        from cogs.ai_core.response_sender import ResponseSender

        sender = ResponseSender()

        channel = MagicMock()
        channel.typing = MagicMock(return_value=AsyncMock())

        # Should not raise
        await sender.send_typing(channel)


# ============================================================================
# Module-Level Instance Tests
# ============================================================================


class TestModuleInstances:
    """Tests for module-level instances."""

    def test_performance_tracker_instance(self):
        """Test performance_tracker module instance."""
        from cogs.ai_core.performance import performance_tracker

        assert performance_tracker is not None

    def test_request_deduplicator_instance(self):
        """Test request_deduplicator module instance."""
        from cogs.ai_core.performance import request_deduplicator

        assert request_deduplicator is not None

    def test_message_queue_instance(self):
        """Test message_queue module instance."""
        from cogs.ai_core.message_queue import message_queue

        assert message_queue is not None

    def test_context_builder_instance(self):
        """Test context_builder module instance."""
        from cogs.ai_core.context_builder import context_builder

        assert context_builder is not None

    def test_response_sender_instance(self):
        """Test response_sender module instance."""
        from cogs.ai_core.response_sender import response_sender

        assert response_sender is not None


# ============================================================================
# Integration Tests
# ============================================================================


class TestModularIntegration:
    """Integration tests for modular components."""

    @pytest.mark.asyncio
    async def test_message_queue_flow(self):
        """Test complete message queue flow."""
        from cogs.ai_core.message_queue import MessageQueue

        queue = MessageQueue()

        # Create mock users
        user1 = MagicMock()
        user1.display_name = "Alice"
        user2 = MagicMock()
        user2.display_name = "Bob"

        channel = MagicMock()

        # Queue messages
        queue.queue_message(123, channel, user1, "Hello")
        queue.queue_message(123, channel, user2, "Hi there")

        # Check state
        assert queue.has_pending(123)
        assert queue.get_pending_count(123) == 2

        # Merge and process
        latest, combined = queue.merge_pending_messages(123)

        assert latest.user == user2
        assert "Alice" in combined
        assert "Bob" in combined

        # Queue should be empty now
        assert not queue.has_pending(123)

    @pytest.mark.asyncio
    async def test_context_and_response_flow(self):
        """Test context building and response sending flow."""
        from cogs.ai_core.context_builder import ContextBuilder
        from cogs.ai_core.response_sender import ResponseSender

        # Build context
        builder = ContextBuilder()
        ctx = await builder.build_context(
            channel_id=123,
            user_id=456,
            message="Test message",
        )

        # Create response
        sender = ResponseSender()

        channel = MagicMock()
        sent_msg = MagicMock(id=12345)
        channel.send = AsyncMock(return_value=sent_msg)

        # Build response using context (verify it doesn't raise)
        _ = ctx.build_system_context()

        result = await sender.send_response(
            channel,
            "AI Response based on context",
            use_webhook=False,
        )

        assert result.success is True

    def test_performance_tracking_flow(self):
        """Test performance tracking flow."""
        from cogs.ai_core.performance import PerformanceTracker, RequestDeduplicator

        tracker = PerformanceTracker()
        dedup = RequestDeduplicator()

        # Simulate request flow
        request_key = dedup.generate_key(123, 456, "test")

        # Check deduplication
        dedup.add_request(request_key)
        assert dedup.is_duplicate(request_key)

        # Track performance
        tracker.record_timing("api_call", 0.5)
        tracker.record_timing("api_call", 0.3)

        stats = tracker.get_stats()
        assert stats["api_call"]["count"] == 2

        # Cleanup
        dedup.remove_request(request_key)
        assert not dedup.is_duplicate(request_key)
