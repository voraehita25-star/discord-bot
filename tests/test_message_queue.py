"""
Tests for cogs.ai_core.core.message_queue module.
"""

import pytest
import asyncio
from unittest.mock import MagicMock
import time


class TestPendingMessageDataclass:
    """Tests for PendingMessage dataclass."""

    def test_create_pending_message(self):
        """Test creating PendingMessage."""
        from cogs.ai_core.core.message_queue import PendingMessage
        
        channel = MagicMock()
        user = MagicMock()
        
        msg = PendingMessage(
            channel=channel,
            user=user,
            message="Hello"
        )
        
        assert msg.channel == channel
        assert msg.user == user
        assert msg.message == "Hello"
        assert msg.generate_response is True

    def test_pending_message_defaults(self):
        """Test PendingMessage default values."""
        from cogs.ai_core.core.message_queue import PendingMessage
        
        msg = PendingMessage(
            channel=MagicMock(),
            user=MagicMock(),
            message="Test"
        )
        
        assert msg.attachments is None
        assert msg.output_channel is None
        assert msg.generate_response is True
        assert msg.user_message_id is None
        assert isinstance(msg.timestamp, float)

    def test_pending_message_with_attachments(self):
        """Test PendingMessage with attachments."""
        from cogs.ai_core.core.message_queue import PendingMessage
        
        attachments = [MagicMock(), MagicMock()]
        
        msg = PendingMessage(
            channel=MagicMock(),
            user=MagicMock(),
            message="Test",
            attachments=attachments
        )
        
        assert msg.attachments == attachments
        assert len(msg.attachments) == 2


class TestMessageQueueInit:
    """Tests for MessageQueue initialization."""

    def test_create_message_queue(self):
        """Test creating MessageQueue."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        assert queue is not None
        assert isinstance(queue.pending_messages, dict)
        assert isinstance(queue.cancel_flags, dict)
        assert isinstance(queue.processing_locks, dict)

    def test_initial_state_empty(self):
        """Test MessageQueue initial state is empty."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        assert len(queue.pending_messages) == 0
        assert len(queue.cancel_flags) == 0


class TestMessageQueueLock:
    """Tests for MessageQueue lock management."""

    def test_get_lock_creates_lock(self):
        """Test get_lock creates a lock if not exists."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        lock = queue.get_lock(12345)
        
        assert isinstance(lock, asyncio.Lock)
        assert 12345 in queue.processing_locks

    def test_get_lock_returns_same_lock(self):
        """Test get_lock returns same lock for same channel."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        lock1 = queue.get_lock(12345)
        lock2 = queue.get_lock(12345)
        
        assert lock1 is lock2

    def test_is_locked_false_initially(self):
        """Test is_locked returns False initially."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        result = queue.is_locked(12345)
        
        assert result is False

    def test_is_locked_false_no_lock(self):
        """Test is_locked returns False when no lock exists."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        result = queue.is_locked(99999)
        
        assert result is False


class TestMessageQueueQueue:
    """Tests for MessageQueue queue operations."""

    def test_queue_message(self):
        """Test queue_message adds message to queue."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        channel = MagicMock()
        user = MagicMock()
        
        queue.queue_message(
            channel_id=12345,
            channel=channel,
            user=user,
            message="Hello"
        )
        
        assert 12345 in queue.pending_messages
        assert len(queue.pending_messages[12345]) == 1

    def test_queue_multiple_messages(self):
        """Test queuing multiple messages."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        channel = MagicMock()
        user = MagicMock()
        
        queue.queue_message(12345, channel, user, "Message 1")
        queue.queue_message(12345, channel, user, "Message 2")
        queue.queue_message(12345, channel, user, "Message 3")
        
        assert len(queue.pending_messages[12345]) == 3

    def test_has_pending_true(self):
        """Test has_pending returns True when messages exist."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        queue.queue_message(12345, MagicMock(), MagicMock(), "Test")
        
        assert queue.has_pending(12345) is True

    def test_has_pending_false(self):
        """Test has_pending returns False when no messages."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        assert queue.has_pending(12345) is False

    def test_get_pending_count(self):
        """Test get_pending_count returns correct count."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        channel = MagicMock()
        user = MagicMock()
        
        queue.queue_message(12345, channel, user, "Message 1")
        queue.queue_message(12345, channel, user, "Message 2")
        
        assert queue.get_pending_count(12345) == 2

    def test_get_pending_count_empty(self):
        """Test get_pending_count returns 0 for empty."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        assert queue.get_pending_count(99999) == 0


class TestMessageQueueCancel:
    """Tests for MessageQueue cancel operations."""

    def test_signal_cancel(self):
        """Test signal_cancel sets cancel flag."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        queue.signal_cancel(12345)
        
        assert queue.cancel_flags[12345] is True

    def test_reset_cancel(self):
        """Test reset_cancel clears cancel flag."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        queue.signal_cancel(12345)
        
        queue.reset_cancel(12345)
        
        assert queue.cancel_flags[12345] is False

    def test_is_cancelled_true(self):
        """Test is_cancelled returns True when cancelled."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        queue.signal_cancel(12345)
        
        assert queue.is_cancelled(12345) is True

    def test_is_cancelled_false(self):
        """Test is_cancelled returns False when not cancelled."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        assert queue.is_cancelled(12345) is False


class TestMessageQueuePop:
    """Tests for MessageQueue pop operations."""

    def test_pop_pending_messages(self):
        """Test pop_pending_messages returns and clears messages."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        channel = MagicMock()
        user = MagicMock()
        
        queue.queue_message(12345, channel, user, "Message 1")
        queue.queue_message(12345, channel, user, "Message 2")
        
        result = queue.pop_pending_messages(12345)
        
        assert len(result) == 2
        assert len(queue.pending_messages[12345]) == 0

    def test_pop_pending_messages_empty(self):
        """Test pop_pending_messages returns empty list when none."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        result = queue.pop_pending_messages(99999)
        
        assert result == []


class TestMessageQueueMerge:
    """Tests for MessageQueue merge operations."""

    def test_merge_single_message(self):
        """Test merge_pending_messages with single message."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        channel = MagicMock()
        user = MagicMock()
        user.display_name = "TestUser"
        
        queue.queue_message(12345, channel, user, "Hello world")
        
        latest, combined = queue.merge_pending_messages(12345)
        
        assert latest is not None
        assert combined == "Hello world"

    def test_merge_multiple_messages(self):
        """Test merge_pending_messages with multiple messages."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        channel = MagicMock()
        
        user1 = MagicMock()
        user1.display_name = "User1"
        user2 = MagicMock()
        user2.display_name = "User2"
        
        queue.queue_message(12345, channel, user1, "Hello")
        queue.queue_message(12345, channel, user2, "World")
        
        latest, combined = queue.merge_pending_messages(12345)
        
        assert latest is not None
        assert "[User1]" in combined
        assert "[User2]" in combined

    def test_merge_empty(self):
        """Test merge_pending_messages with no messages."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        latest, combined = queue.merge_pending_messages(99999)
        
        assert latest is None
        assert combined == ""


class TestMessageQueueLockTimeout:
    """Tests for MessageQueue lock timeout operations."""

    @pytest.mark.asyncio
    async def test_acquire_lock_with_timeout_success(self):
        """Test acquire_lock_with_timeout success."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        result = await queue.acquire_lock_with_timeout(12345, timeout=5.0)
        
        assert result is True
        assert queue.is_locked(12345) is True
        
        # Cleanup
        queue.release_lock(12345)

    @pytest.mark.asyncio
    async def test_release_lock(self):
        """Test release_lock releases the lock."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        await queue.acquire_lock_with_timeout(12345)
        queue.release_lock(12345)
        
        assert queue.is_locked(12345) is False

    def test_get_lock_time(self):
        """Test get_lock_time returns lock time."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        # Initially no lock time
        assert queue.get_lock_time(12345) is None


class TestMessageQueueCleanup:
    """Tests for MessageQueue cleanup operations."""

    @pytest.mark.asyncio
    async def test_cleanup_stale_locks_none(self):
        """Test cleanup_stale_locks returns 0 when no stale locks."""
        from cogs.ai_core.core.message_queue import MessageQueue
        
        queue = MessageQueue()
        
        result = queue.cleanup_stale_locks(max_age=300.0)
        
        assert result == 0


class TestGlobalMessageQueue:
    """Tests for global message_queue instance."""

    def test_global_instance_exists(self):
        """Test global message_queue exists."""
        from cogs.ai_core.core.message_queue import message_queue
        
        assert message_queue is not None

    def test_global_instance_is_queue(self):
        """Test global message_queue is MessageQueue."""
        from cogs.ai_core.core.message_queue import message_queue, MessageQueue
        
        assert isinstance(message_queue, MessageQueue)


class TestBackwardCompatibility:
    """Tests for backward compatibility re-exports."""

    def test_import_from_message_queue(self):
        """Test importing from cogs.ai_core.message_queue."""
        from cogs.ai_core.message_queue import (
            MessageQueue,
            PendingMessage,
            message_queue,
        )
        
        assert MessageQueue is not None
        assert PendingMessage is not None
        assert message_queue is not None
