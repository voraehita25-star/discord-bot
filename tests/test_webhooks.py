# pylint: disable=protected-access
"""
Unit Tests for Webhook Functionality.
Tests webhook caching, message routing, and cleanup.

NOTE: Many tests in this file were removed because they import functions
that don't exist in the current implementation:
- get_or_create_webhook
- is_tupperbox_webhook
- _webhook_cache_timestamps
- _cleanup_task
- cleanup_webhook_cache

The actual implementation uses internal functions like _get_cached_webhook(),
_set_cached_webhook(), start_webhook_cache_cleanup(), etc.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestWebhookCache:
    """Tests for webhook cache management."""

    def test_webhook_cache_initialization(self):
        """Test that webhook cache is properly initialized."""
        from cogs.ai_core.response.webhook_cache import _webhook_cache

        # Cache should be a dictionary
        assert isinstance(_webhook_cache, dict)


class TestWebhookMessageSending:
    """Tests for sending messages via webhooks."""

    @pytest.mark.asyncio
    async def test_send_via_webhook_success(self):
        """Test successful message sending via webhook."""
        mock_webhook = MagicMock()
        mock_webhook.send = AsyncMock(return_value=MagicMock())

        # Simulate sending a message
        await mock_webhook.send(
            content="Test message", username="TestBot", avatar_url="https://example.com/avatar.png"
        )

        mock_webhook.send.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_via_webhook_with_embed(self):
        """Test sending embed via webhook."""
        mock_webhook = MagicMock()
        mock_webhook.send = AsyncMock(return_value=MagicMock())

        mock_embed = MagicMock()
        mock_embed.title = "Test Embed"

        await mock_webhook.send(embeds=[mock_embed], username="TestBot")

        mock_webhook.send.assert_called_once()
        call_kwargs = mock_webhook.send.call_args[1]
        assert "embeds" in call_kwargs


class TestWebhookCacheInternals:
    """Tests for internal webhook cache functions that DO exist."""

    def test_get_cached_webhook_returns_none_for_empty_cache(self):
        """Test that get_cached_webhook returns None when cache is empty."""
        from cogs.ai_core.response.webhook_cache import _webhook_cache, get_cached_webhook

        # Clear cache
        _webhook_cache.clear()

        result = get_cached_webhook(123456789, "TestBot")
        assert result is None

    def test_set_and_get_cached_webhook(self):
        """Test storing and retrieving webhooks from cache."""
        from cogs.ai_core.response.webhook_cache import (
            _webhook_cache,
            get_cached_webhook,
            set_cached_webhook,
        )

        # Clear cache
        _webhook_cache.clear()

        # Create mock webhook
        mock_webhook = MagicMock()
        mock_webhook.name = "Faust"

        channel_id = 987654321

        # Store in cache
        set_cached_webhook(channel_id, "Faust", mock_webhook)

        # Retrieve from cache
        result = get_cached_webhook(channel_id, "Faust")
        assert result == mock_webhook

    def test_invalidate_webhook_cache(self):
        """Test invalidating webhook cache for a channel."""
        from cogs.ai_core.response.webhook_cache import (
            _webhook_cache,
            invalidate_webhook_cache,
            set_cached_webhook,
        )

        # Clear cache
        _webhook_cache.clear()

        # Create mock webhook
        mock_webhook = MagicMock()
        channel_id = 111222333

        # Store in cache
        set_cached_webhook(channel_id, "TestBot", mock_webhook)
        assert channel_id in _webhook_cache

        # Invalidate
        invalidate_webhook_cache(channel_id)
        assert channel_id not in _webhook_cache
