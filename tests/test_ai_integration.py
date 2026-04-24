# pylint: disable=protected-access
"""
Integration Tests for AI Flow.
Tests the complete AI request flow from message to response.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAIFlow:
    """Integration tests for AI chat flow."""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot instance."""
        bot = MagicMock()
        bot.user = MagicMock()
        bot.user.id = 123456789
        bot.user.mention = "<@123456789>"
        return bot

    @pytest.fixture
    def mock_channel(self):
        """Create a mock channel."""
        channel = MagicMock()
        channel.id = 987654321
        channel.name = "test-channel"
        channel.typing = MagicMock(return_value=AsyncMock())
        channel.send = AsyncMock(return_value=MagicMock(id=111))
        return channel

    @pytest.fixture
    def mock_message(self, mock_channel):
        """Create a mock message."""
        message = MagicMock()
        message.id = 555666777
        message.content = "Hello, test message"
        message.channel = mock_channel
        message.author = MagicMock()
        message.author.id = 111222333
        message.author.display_name = "TestUser"
        message.author.avatar = MagicMock()
        message.author.avatar.url = "https://example.com/avatar.png"
        message.guild = MagicMock()
        message.guild.id = 444555666
        message.attachments = []
        return message

    @pytest.mark.asyncio
    async def test_chat_manager_initialization(self, mock_bot):
        """Test ChatManager initializes correctly."""
        from cogs.ai_core.logic import ChatManager

        manager = ChatManager(mock_bot)

        assert manager.bot == mock_bot
        assert isinstance(manager.chats, dict)
        assert isinstance(manager.seen_users, dict)

    @pytest.mark.asyncio
    async def test_session_creation(self, mock_bot, mock_channel):
        """Test that sessions can be stored in chats dict."""
        from cogs.ai_core.logic import ChatManager

        manager = ChatManager(mock_bot)
        channel_id = mock_channel.id

        # Session should not exist initially
        assert channel_id not in manager.chats

        # Manually create a session (simulating what the manager does internally)
        manager.chats[channel_id] = {"history": [], "thinking_enabled": True}

        # Session should now exist
        assert channel_id in manager.chats
        assert "history" in manager.chats[channel_id]

    @pytest.mark.asyncio
    async def test_rate_limiting_flow(self, mock_bot, mock_message):
        """Test rate limiting integration."""
        from utils.reliability.rate_limiter import rate_limiter

        # Check initial state
        allowed, retry, _msg = await rate_limiter.check(
            "gemini_api", user_id=mock_message.author.id
        )

        # Should be allowed initially
        assert allowed
        assert retry == 0.0

    @pytest.mark.asyncio
    async def test_circuit_breaker_integration(self):
        """Test circuit breaker allows requests when closed."""
        from utils.reliability.circuit_breaker import gemini_circuit

        # Circuit should be closed by default
        assert gemini_circuit.can_execute()

    @pytest.mark.asyncio
    async def test_fallback_system(self):
        """Test fallback system provides responses."""
        from cogs.ai_core.fallback_responses import FallbackReason, fallback_system

        # Should not use fallback when circuit is healthy
        if not fallback_system.should_use_fallback():
            # Get a fallback anyway for testing
            response = fallback_system.get_by_reason(FallbackReason.API_ERROR)

            assert response.message is not None
            assert len(response.message) > 0

    @pytest.mark.asyncio
    async def test_history_persistence(self, mock_bot, mock_channel):
        """Test that history is saved and loaded correctly.

        Note: This test mocks database operations to prevent writing
        mock data (channel_id=987654321) to production database.
        """
        from unittest.mock import AsyncMock

        test_history = [
            {"role": "user", "parts": ["Test message 1"]},
            {"role": "model", "parts": ["Test response 1"]},
        ]

        # Create chat_data dict as expected by save_history
        chat_data = {"history": test_history, "thinking_enabled": True}

        # Mock the database module to prevent production writes
        with patch("cogs.ai_core.storage.DATABASE_AVAILABLE", False):
            # Import after patching
            from cogs.ai_core.storage import load_history, save_history

            # Mock the JSON file operations
            with patch("cogs.ai_core.storage._save_history_json", new_callable=AsyncMock):
                with patch(
                    "cogs.ai_core.storage._load_history_json", new_callable=AsyncMock
                ) as mock_load:
                    mock_load.return_value = test_history

                    # Save history (mocked)
                    await save_history(mock_bot, mock_channel.id, chat_data)

                    # Load history (returns mocked data)
                    loaded = await load_history(mock_bot, mock_channel.id)

                    # Should have the mocked history
                    assert isinstance(loaded, list)
                    assert len(loaded) == 2


class TestTokenTracking:
    """Tests for token tracking integration."""

    @pytest.mark.asyncio
    async def test_token_recording(self):
        """Test token usage is recorded."""
        from utils.monitoring.token_tracker import token_tracker

        user_id = 999888777

        # Record usage
        token_tracker.record(user_id=user_id, input_tokens=500, output_tokens=150)

        # Get stats
        stats = token_tracker.get_user_stats(user_id)

        assert stats is not None
        assert stats.total_input >= 500
        assert stats.total_output >= 150

    @pytest.mark.asyncio
    async def test_global_stats(self):
        """Test global stats are tracked."""
        from utils.monitoring.token_tracker import token_tracker

        stats = token_tracker.get_global_stats()

        assert "total_tokens" in stats
        assert "unique_users" in stats


class TestFeedbackCollection:
    """Tests for feedback collection system."""

    def test_feedback_tracking(self):
        """Test message tracking for feedback."""
        from utils.monitoring.feedback import feedback_collector

        message_id = 123456789
        channel_id = 987654321

        # Track message
        feedback_collector.track_message(message_id, channel_id)

        # Should be tracked
        assert feedback_collector.is_tracked(message_id)

    def test_reaction_processing(self):
        """Test reaction processing creates feedback."""
        from utils.monitoring.feedback import FeedbackType, feedback_collector

        message_id = 111222333
        channel_id = 444555666
        user_id = 777888999

        # Track message first
        feedback_collector.track_message(message_id, channel_id)

        # Process positive reaction
        entry = feedback_collector.process_reaction(message_id, user_id, "👍")

        assert entry is not None
        assert entry.feedback_type == FeedbackType.POSITIVE

    def test_stats_calculation(self):
        """Test feedback stats are calculated correctly."""
        from utils.monitoring.feedback import feedback_collector

        stats = feedback_collector.get_stats()

        assert hasattr(stats, "satisfaction_rate")
        assert hasattr(stats, "total_feedback")


class TestCacheIntegration:
    """Tests for AI cache integration."""

    @pytest.mark.asyncio
    async def test_cache_operations(self):
        """Test cache get/set operations."""
        from cogs.ai_core.cache.ai_cache import ai_cache

        test_message = "Hello, how are you?"
        test_response = "This is a cached response that is long enough to cache"

        # Set cache (uses message, response, context_hash, intent)
        ai_cache.set(test_message, test_response, context_hash="test123")

        # Get cache (uses message, context_hash)
        cached = ai_cache.get(test_message, context_hash="test123")

        # Should match
        assert cached == test_response

    @pytest.mark.asyncio
    async def test_cache_stats(self):
        """Test cache statistics."""
        from cogs.ai_core.cache.ai_cache import ai_cache

        stats = ai_cache.get_stats()

        assert hasattr(stats, "total_entries")
        assert hasattr(stats, "hit_rate")
