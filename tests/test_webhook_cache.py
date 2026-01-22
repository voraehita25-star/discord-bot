"""
Tests for cogs/ai_core/response/webhook_cache.py

Comprehensive tests for webhook caching functionality.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetCachedWebhook:
    """Tests for get_cached_webhook function."""

    def test_get_no_cache(self):
        """Test getting from empty cache."""
        # Clear cache first
        from cogs.ai_core.response import webhook_cache
        from cogs.ai_core.response.webhook_cache import get_cached_webhook
        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()

        result = get_cached_webhook(12345, "TestWebhook")

        assert result is None

    def test_get_cached_webhook_valid(self):
        """Test getting valid cached webhook."""
        from cogs.ai_core.response import webhook_cache

        # Setup cache
        mock_webhook = MagicMock()
        webhook_cache._webhook_cache[12345] = {"TestBot": mock_webhook}
        webhook_cache._webhook_cache_time[12345] = time.time()

        result = webhook_cache.get_cached_webhook(12345, "TestBot")

        assert result is mock_webhook

        # Cleanup
        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()

    def test_get_cached_webhook_expired(self):
        """Test getting expired cached webhook returns None."""
        from cogs.ai_core.response import webhook_cache

        # Setup expired cache
        mock_webhook = MagicMock()
        webhook_cache._webhook_cache[12345] = {"TestBot": mock_webhook}
        webhook_cache._webhook_cache_time[12345] = time.time() - 1000  # Expired

        result = webhook_cache.get_cached_webhook(12345, "TestBot")

        assert result is None

        # Cleanup
        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()

    def test_get_cached_webhook_wrong_name(self):
        """Test getting wrong webhook name returns None."""
        from cogs.ai_core.response import webhook_cache

        # Setup cache
        mock_webhook = MagicMock()
        webhook_cache._webhook_cache[12345] = {"TestBot": mock_webhook}
        webhook_cache._webhook_cache_time[12345] = time.time()

        result = webhook_cache.get_cached_webhook(12345, "WrongName")

        assert result is None

        # Cleanup
        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()


class TestSetCachedWebhook:
    """Tests for set_cached_webhook function."""

    def test_set_new_channel(self):
        """Test setting webhook for new channel."""
        from cogs.ai_core.response import webhook_cache

        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()

        mock_webhook = MagicMock()
        webhook_cache.set_cached_webhook(12345, "TestBot", mock_webhook)

        assert 12345 in webhook_cache._webhook_cache
        assert webhook_cache._webhook_cache[12345]["TestBot"] is mock_webhook
        assert 12345 in webhook_cache._webhook_cache_time

        # Cleanup
        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()

    def test_set_existing_channel(self):
        """Test setting webhook for existing channel."""
        from cogs.ai_core.response import webhook_cache

        # Setup existing cache
        old_webhook = MagicMock()
        webhook_cache._webhook_cache[12345] = {"OldBot": old_webhook}
        webhook_cache._webhook_cache_time[12345] = time.time() - 100

        new_webhook = MagicMock()
        webhook_cache.set_cached_webhook(12345, "NewBot", new_webhook)

        assert webhook_cache._webhook_cache[12345]["NewBot"] is new_webhook
        assert webhook_cache._webhook_cache[12345]["OldBot"] is old_webhook

        # Cleanup
        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()


class TestInvalidateWebhookCache:
    """Tests for invalidate_webhook_cache function."""

    def test_invalidate_specific_webhook(self):
        """Test invalidating specific webhook by name."""
        from cogs.ai_core.response import webhook_cache

        # Setup
        mock_wh1 = MagicMock()
        mock_wh2 = MagicMock()
        webhook_cache._webhook_cache[12345] = {"Bot1": mock_wh1, "Bot2": mock_wh2}
        webhook_cache._webhook_cache_time[12345] = time.time()

        webhook_cache.invalidate_webhook_cache(12345, "Bot1")

        assert "Bot1" not in webhook_cache._webhook_cache[12345]
        assert "Bot2" in webhook_cache._webhook_cache[12345]

        # Cleanup
        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()

    def test_invalidate_all_channel_webhooks(self):
        """Test invalidating all webhooks for a channel."""
        from cogs.ai_core.response import webhook_cache

        # Setup
        mock_wh1 = MagicMock()
        mock_wh2 = MagicMock()
        webhook_cache._webhook_cache[12345] = {"Bot1": mock_wh1, "Bot2": mock_wh2}
        webhook_cache._webhook_cache_time[12345] = time.time()

        webhook_cache.invalidate_webhook_cache(12345)

        assert 12345 not in webhook_cache._webhook_cache
        assert 12345 not in webhook_cache._webhook_cache_time

        # Cleanup
        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()

    def test_invalidate_nonexistent_channel(self):
        """Test invalidating non-existent channel doesn't raise."""
        from cogs.ai_core.response import webhook_cache

        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()

        # Should not raise
        webhook_cache.invalidate_webhook_cache(99999)


class TestInvalidateWebhookCacheOnChannelDelete:
    """Tests for invalidate_webhook_cache_on_channel_delete function."""

    def test_invalidate_on_delete(self):
        """Test invalidating on channel delete."""
        from cogs.ai_core.response import webhook_cache

        # Setup
        mock_webhook = MagicMock()
        webhook_cache._webhook_cache[12345] = {"TestBot": mock_webhook}
        webhook_cache._webhook_cache_time[12345] = time.time()

        webhook_cache.invalidate_webhook_cache_on_channel_delete(12345)

        assert 12345 not in webhook_cache._webhook_cache

        # Cleanup
        webhook_cache._webhook_cache.clear()
        webhook_cache._webhook_cache_time.clear()


class TestStartStopCleanupTask:
    """Tests for start/stop cleanup task functions."""

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_start_cleanup_task(self):
        """Test starting cleanup task."""
        from cogs.ai_core.response import webhook_cache

        mock_bot = MagicMock()
        mock_task = MagicMock()
        mock_bot.loop.create_task.return_value = mock_task

        webhook_cache._webhook_cache_cleanup_task = None
        webhook_cache.start_webhook_cache_cleanup(mock_bot)

        mock_bot.loop.create_task.assert_called_once()
        assert webhook_cache._webhook_cache_cleanup_task is mock_task

    def test_start_cleanup_task_already_running(self):
        """Test start doesn't create new task if already running."""
        from cogs.ai_core.response import webhook_cache

        mock_task = MagicMock()
        mock_task.done.return_value = False
        webhook_cache._webhook_cache_cleanup_task = mock_task

        mock_bot = MagicMock()
        webhook_cache.start_webhook_cache_cleanup(mock_bot)

        mock_bot.loop.create_task.assert_not_called()

    def test_stop_cleanup_task(self):
        """Test stopping cleanup task."""
        from cogs.ai_core.response import webhook_cache

        # Setup
        mock_task = MagicMock()
        mock_task.done.return_value = False
        webhook_cache._webhook_cache_cleanup_task = mock_task
        webhook_cache._webhook_cache[12345] = {"Bot": MagicMock()}

        webhook_cache.stop_webhook_cache_cleanup()

        mock_task.cancel.assert_called_once()
        assert webhook_cache._webhook_cache_cleanup_task is None
        assert len(webhook_cache._webhook_cache) == 0

    def test_stop_cleanup_task_not_running(self):
        """Test stopping when no task running."""
        from cogs.ai_core.response import webhook_cache

        webhook_cache._webhook_cache_cleanup_task = None

        # Should not raise
        webhook_cache.stop_webhook_cache_cleanup()


class TestModuleExports:
    """Tests for module exports."""

    def test_all_exports(self):
        """Test __all__ exports are defined."""
        from cogs.ai_core.response.webhook_cache import __all__

        assert "get_cached_webhook" in __all__
        assert "set_cached_webhook" in __all__
        assert "invalidate_webhook_cache" in __all__
        assert "invalidate_webhook_cache_on_channel_delete" in __all__
        assert "start_webhook_cache_cleanup" in __all__
        assert "stop_webhook_cache_cleanup" in __all__
        assert "WEBHOOK_CACHE_TTL" in __all__

    def test_webhook_cache_ttl(self):
        """Test WEBHOOK_CACHE_TTL constant."""
        from cogs.ai_core.response.webhook_cache import WEBHOOK_CACHE_TTL

        assert WEBHOOK_CACHE_TTL == 600
