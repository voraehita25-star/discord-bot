"""
Tests for AI Core Modular Components
Comprehensive tests for performance and message_queue modules.
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
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        assert tracker._metrics is not None
        assert "api_call" in tracker._metrics

    def test_record_timing(self):
        """Test recording timing for a step."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.5)

        assert "api_call" in tracker._metrics
        assert len(tracker._metrics["api_call"]) == 1
        assert tracker._metrics["api_call"][0] == 0.5

    def test_record_multiple_timings(self):
        """Test recording multiple timings for same step."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        for i in range(5):
            tracker.record_timing("api_call", 0.1 * (i + 1))

        assert len(tracker._metrics["api_call"]) == 5

    def test_max_samples_limit(self):
        """Test that max_samples limit is enforced."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        # Record more than PERFORMANCE_SAMPLES_MAX (100)
        for i in range(150):
            tracker.record_timing("test_step", float(i))

        # Should only keep last 100 samples (PERFORMANCE_SAMPLES_MAX)
        assert len(tracker._metrics["test_step"]) == 100

    def test_get_stats_empty(self):
        """Test get_stats with only initialized steps (no data added)."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        stats = tracker.get_stats()
        # Default steps exist but have no data
        assert "api_call" in stats
        assert stats["api_call"]["count"] == 0

    def test_get_stats_with_data(self):
        """Test get_stats with recorded data."""
        from cogs.ai_core.core.performance import PerformanceTracker

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
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("rag_search", 0.05)
        tracker.record_timing("streaming", 0.15)

        stats = tracker.get_step_stats("rag_search")
        assert stats["count"] == 1
        assert stats["avg_ms"] == 50.0

    def test_clear_metrics(self):
        """Test clearing metrics."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.5)
        tracker.clear_metrics()

        assert len(tracker._metrics["api_call"]) == 0

    def test_clear_single_step(self):
        """Test clearing a single step."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.5)
        tracker.record_timing("rag_search", 0.1)
        tracker.clear_metrics("api_call")

        assert len(tracker._metrics["api_call"]) == 0
        assert len(tracker._metrics["rag_search"]) == 1

    def test_get_summary(self):
        """Test getting performance summary."""
        from cogs.ai_core.core.performance import PerformanceTracker

        tracker = PerformanceTracker()
        tracker.record_timing("api_call", 0.5)

        summary = tracker.get_summary()
        assert "📊 Performance Summary:" in summary
        assert "api_call" in summary


class TestRequestDeduplicator:
    """Tests for RequestDeduplicator class."""

    def test_init(self):
        """Test RequestDeduplicator initialization."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        assert dedup._pending_requests == {}

    def test_is_duplicate_new_request(self):
        """Test that new request is not duplicate."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        is_dup = dedup.is_duplicate("key1")

        assert is_dup is False  # Not in pending yet

        # Add it
        dedup.add_request("key1")
        assert "key1" in dedup._pending_requests

    def test_is_duplicate_existing_request(self):
        """Test that existing request is duplicate."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        dedup.add_request("key1")  # First add
        is_dup = dedup.is_duplicate("key1")  # Now check

        assert is_dup is True

    def test_remove_request(self):
        """Test removing a request."""
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        dedup.add_request("key1")
        dedup.remove_request("key1")

        assert "key1" not in dedup._pending_requests

    def test_cleanup_old_requests(self):
        """Test cleanup of old requests."""
        from cogs.ai_core.core.performance import RequestDeduplicator

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
        from cogs.ai_core.core.performance import RequestDeduplicator

        dedup = RequestDeduplicator()
        key = dedup.generate_key(123, 456, "test message")

        assert "123" in key
        assert "456" in key

    def test_get_pending_count(self):
        """Test getting pending count."""
        from cogs.ai_core.core.performance import RequestDeduplicator

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
        from cogs.ai_core.core.message_queue import PendingMessage

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
        from cogs.ai_core.core.message_queue import PendingMessage

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
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        assert queue.pending_messages == {}
        assert queue.cancel_flags == {}
        assert queue.processing_locks == {}

    async def test_get_lock(self):
        """Test getting a lock for a channel."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        lock = queue.get_lock_sync(123)

        assert isinstance(lock, asyncio.Lock)
        assert 123 in queue.processing_locks

    async def test_get_lock_same_channel(self):
        """Test getting same lock for same channel."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        lock1 = queue.get_lock_sync(123)
        lock2 = queue.get_lock_sync(123)

        assert lock1 is lock2

    def test_queue_message(self):
        """Test queuing a message."""
        from cogs.ai_core.core.message_queue import MessageQueue

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
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        queue.signal_cancel(123)

        assert queue.cancel_flags[123] is True

    def test_reset_cancel(self):
        """Test resetting cancel flag."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        queue.signal_cancel(123)
        queue.reset_cancel(123)

        assert queue.cancel_flags[123] is False

    def test_is_cancelled(self):
        """Test checking if cancelled."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        assert queue.is_cancelled(123) is False

        queue.signal_cancel(123)
        assert queue.is_cancelled(123) is True

    def test_has_pending(self):
        """Test checking for pending messages."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        assert queue.has_pending(123) is False

        queue.queue_message(123, MagicMock(), MagicMock(), "Test")
        assert queue.has_pending(123) is True

    def test_get_pending_count(self):
        """Test getting pending message count."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        assert queue.get_pending_count(123) == 0

        queue.queue_message(123, MagicMock(), MagicMock(), "Test1")
        queue.queue_message(123, MagicMock(), MagicMock(), "Test2")
        assert queue.get_pending_count(123) == 2

    def test_pop_pending_messages(self):
        """Test popping pending messages."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        queue.queue_message(123, MagicMock(), MagicMock(), "Test1")
        queue.queue_message(123, MagicMock(), MagicMock(), "Test2")
        queue.signal_cancel(123)

        messages = queue.pop_pending_messages(123)

        assert len(messages) == 2
        assert queue.pending_messages[123] == []
        # cancel_flags entry is removed (not set to False) so unbounded
        # growth doesn't accumulate per channel.
        assert 123 not in queue.cancel_flags

    def test_merge_pending_messages(self):
        """Test merging pending messages."""
        from cogs.ai_core.core.message_queue import MessageQueue

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
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        user = MagicMock()
        user.display_name = "User"

        queue.queue_message(123, MagicMock(), user, "Hello")

        latest, combined = queue.merge_pending_messages(123)

        assert combined == "Hello"

    def test_merge_empty_queue(self):
        """Test merging empty queue."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()

        latest, combined = queue.merge_pending_messages(123)

        assert latest is None
        assert combined == ""

    @pytest.mark.asyncio
    async def test_acquire_lock_with_timeout(self):
        """Test acquiring lock with timeout."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        result = await queue.acquire_lock_with_timeout(123, timeout=5.0)

        assert result is True
        assert queue.is_locked(123) is True

        # Release for cleanup
        queue.release_lock(123)

    @pytest.mark.asyncio
    async def test_acquire_lock_timeout(self):
        """Test lock acquisition timeout."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        lock = queue.get_lock_sync(123)
        await lock.acquire()  # Lock it first

        # Try to acquire again - should timeout
        result = await queue.acquire_lock_with_timeout(123, timeout=0.1)

        assert result is False

        # Cleanup
        lock.release()

    async def test_release_lock(self):
        """Test releasing a lock."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        # get_lock_sync requires a running asyncio loop (asserts via
        # asyncio._get_running_loop()), so this test must be async.
        _ = queue.get_lock_sync(123)  # Lock created for side effect

        # Acquire then release on the test's running loop.
        await queue.acquire_lock_with_timeout(123)
        queue.release_lock(123)

        assert queue.is_locked(123) is False

    async def test_cleanup_stale_locks(self):
        """Test detecting stale locks (no longer force-releases)."""
        from cogs.ai_core.core.message_queue import MessageQueue

        queue = MessageQueue()
        # Add old lock time
        queue._lock_times[123] = time.time() - 400  # 400 seconds ago
        # get_lock_sync requires a running asyncio loop, so this test is async.
        queue.get_lock_sync(123)

        # cleanup_stale_locks now only detects stale locks (doesn't release)
        stale_count = queue.cleanup_stale_locks(max_age=300.0)

        # Should detect 1 stale lock
        assert stale_count == 1
        # Lock time should still be present (not released)
        assert 123 in queue._lock_times


# ============================================================================
# Module-Level Instance Tests
# ============================================================================


class TestModuleInstances:
    """Tests for module-level instances."""

    def test_performance_tracker_instance(self):
        """Test performance_tracker module instance."""
        from cogs.ai_core.core.performance import performance_tracker

        assert performance_tracker is not None

    def test_request_deduplicator_instance(self):
        """Test request_deduplicator module instance."""
        from cogs.ai_core.core.performance import request_deduplicator

        assert request_deduplicator is not None

    def test_message_queue_instance(self):
        """Test message_queue module instance."""
        from cogs.ai_core.core.message_queue import message_queue

        assert message_queue is not None


# ============================================================================
# Integration Tests
# ============================================================================


class TestModularIntegration:
    """Integration tests for modular components."""

    @pytest.mark.asyncio
    async def test_message_queue_flow(self):
        """Test complete message queue flow."""
        from cogs.ai_core.core.message_queue import MessageQueue

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

    def test_performance_tracking_flow(self):
        """Test performance tracking flow."""
        from cogs.ai_core.core.performance import PerformanceTracker, RequestDeduplicator

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
