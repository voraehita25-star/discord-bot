"""
Tests for utils.monitoring.feedback module.
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest


class TestFeedbackType:
    """Tests for FeedbackType enum."""

    def test_positive_type(self):
        """Test POSITIVE type."""
        from utils.monitoring.feedback import FeedbackType

        assert FeedbackType.POSITIVE.value == "positive"

    def test_negative_type(self):
        """Test NEGATIVE type."""
        from utils.monitoring.feedback import FeedbackType

        assert FeedbackType.NEGATIVE.value == "negative"

    def test_neutral_type(self):
        """Test NEUTRAL type."""
        from utils.monitoring.feedback import FeedbackType

        assert FeedbackType.NEUTRAL.value == "neutral"

    def test_helpful_type(self):
        """Test HELPFUL type."""
        from utils.monitoring.feedback import FeedbackType

        assert FeedbackType.HELPFUL.value == "helpful"

    def test_funny_type(self):
        """Test FUNNY type."""
        from utils.monitoring.feedback import FeedbackType

        assert FeedbackType.FUNNY.value == "funny"

    def test_length_too_short(self):
        """Test LENGTH_TOO_SHORT type."""
        from utils.monitoring.feedback import FeedbackType

        assert FeedbackType.LENGTH_TOO_SHORT.value == "too_short"

    def test_length_too_long(self):
        """Test LENGTH_TOO_LONG type."""
        from utils.monitoring.feedback import FeedbackType

        assert FeedbackType.LENGTH_TOO_LONG.value == "too_long"


class TestReactionMap:
    """Tests for REACTION_MAP."""

    def test_reaction_map_exists(self):
        """Test REACTION_MAP exists."""
        from utils.monitoring.feedback import REACTION_MAP

        assert REACTION_MAP is not None
        assert isinstance(REACTION_MAP, dict)

    def test_thumbs_up_maps_to_positive(self):
        """Test 👍 maps to POSITIVE."""
        from utils.monitoring.feedback import REACTION_MAP, FeedbackType

        assert REACTION_MAP["👍"] == FeedbackType.POSITIVE

    def test_thumbs_down_maps_to_negative(self):
        """Test 👎 maps to NEGATIVE."""
        from utils.monitoring.feedback import REACTION_MAP, FeedbackType

        assert REACTION_MAP["👎"] == FeedbackType.NEGATIVE

    def test_thinking_maps_to_neutral(self):
        """Test 🤔 maps to NEUTRAL."""
        from utils.monitoring.feedback import REACTION_MAP, FeedbackType

        assert REACTION_MAP["🤔"] == FeedbackType.NEUTRAL


class TestFeedbackEntry:
    """Tests for FeedbackEntry dataclass."""

    def test_create_feedback_entry(self):
        """Test creating FeedbackEntry."""
        from utils.monitoring.feedback import FeedbackEntry, FeedbackType

        entry = FeedbackEntry(
            message_id=123, channel_id=456, user_id=789, feedback_type=FeedbackType.POSITIVE
        )

        assert entry.message_id == 123
        assert entry.channel_id == 456
        assert entry.user_id == 789
        assert entry.feedback_type == FeedbackType.POSITIVE

    def test_feedback_entry_default_timestamp(self):
        """Test FeedbackEntry has default timestamp."""
        from utils.monitoring.feedback import FeedbackEntry, FeedbackType

        before = time.time()
        entry = FeedbackEntry(
            message_id=1, channel_id=2, user_id=3, feedback_type=FeedbackType.NEUTRAL
        )
        after = time.time()

        assert before <= entry.timestamp <= after

    def test_feedback_entry_with_context(self):
        """Test FeedbackEntry with context."""
        from utils.monitoring.feedback import FeedbackEntry, FeedbackType

        entry = FeedbackEntry(
            message_id=1,
            channel_id=2,
            user_id=3,
            feedback_type=FeedbackType.HELPFUL,
            context="Test response",
        )

        assert entry.context == "Test response"


class TestFeedbackStats:
    """Tests for FeedbackStats dataclass."""

    def test_create_feedback_stats(self):
        """Test creating FeedbackStats."""
        from utils.monitoring.feedback import FeedbackStats

        stats = FeedbackStats()

        assert stats.total_feedback == 0
        assert stats.positive_count == 0
        assert stats.negative_count == 0

    def test_satisfaction_rate_empty(self):
        """Test satisfaction_rate with no feedback."""
        from utils.monitoring.feedback import FeedbackStats

        stats = FeedbackStats()

        assert stats.satisfaction_rate == 0

    def test_satisfaction_rate_with_feedback(self):
        """Test satisfaction_rate calculation."""
        from utils.monitoring.feedback import FeedbackStats

        stats = FeedbackStats(total_feedback=10, positive_count=7, negative_count=3)

        assert stats.satisfaction_rate == 0.7

    def test_negative_rate_empty(self):
        """Test negative_rate with no feedback."""
        from utils.monitoring.feedback import FeedbackStats

        stats = FeedbackStats()

        assert stats.negative_rate == 0

    def test_negative_rate_with_feedback(self):
        """Test negative_rate calculation."""
        from utils.monitoring.feedback import FeedbackStats

        stats = FeedbackStats(total_feedback=10, positive_count=7, negative_count=3)

        assert stats.negative_rate == 0.3


class TestFeedbackCollector:
    """Tests for FeedbackCollector class."""

    def test_create_collector(self):
        """Test creating FeedbackCollector."""
        from utils.monitoring.feedback import FeedbackCollector

        collector = FeedbackCollector()
        assert collector is not None

    def test_track_message(self):
        """Test track_message method."""
        from utils.monitoring.feedback import FeedbackCollector

        collector = FeedbackCollector()
        collector.track_message(123, 456)

        assert 123 in collector._tracked_messages

    def test_process_reaction_positive(self):
        """Test processing positive reaction."""
        from utils.monitoring.feedback import FeedbackCollector, FeedbackType

        collector = FeedbackCollector()
        collector.track_message(123, 456)

        result = collector.process_reaction(123, 789, "👍")

        assert result is not None
        assert result.feedback_type == FeedbackType.POSITIVE

    def test_process_reaction_unknown_emoji(self):
        """Test processing unknown emoji."""
        from utils.monitoring.feedback import FeedbackCollector

        collector = FeedbackCollector()
        collector.track_message(123, 456)

        result = collector.process_reaction(123, 789, "🎉")

        assert result is None

    def test_process_reaction_untracked_message(self):
        """Test processing reaction on untracked message."""
        from utils.monitoring.feedback import FeedbackCollector

        collector = FeedbackCollector()

        result = collector.process_reaction(999, 789, "👍")

        assert result is None

    def test_get_stats(self):
        """Test get_stats method."""
        from utils.monitoring.feedback import FeedbackCollector, FeedbackStats

        collector = FeedbackCollector()
        stats = collector.get_stats()

        assert isinstance(stats, FeedbackStats)

    def test_get_stats_after_feedback(self):
        """Test get_stats after recording feedback."""
        from utils.monitoring.feedback import FeedbackCollector

        collector = FeedbackCollector()
        collector.track_message(123, 456)
        collector.process_reaction(123, 789, "👍")

        stats = collector.get_stats()

        assert stats.total_feedback >= 1
        assert stats.positive_count >= 1


class TestFeedbackCollectorSingleton:
    """Tests for feedback_collector singleton."""

    def test_singleton_is_collector(self):
        """Test singleton is FeedbackCollector instance."""
        from utils.monitoring.feedback import FeedbackCollector, feedback_collector

        assert isinstance(feedback_collector, FeedbackCollector)


class TestMaybeTrackFeedbackProducer:
    """Tests for ChatManager._maybe_track_feedback (the producer wiring)."""

    @staticmethod
    def _bare_manager():
        """A ChatManager with no __init__ — the helper only uses module globals."""
        from cogs.ai_core.logic import ChatManager

        return ChatManager.__new__(ChatManager)

    @pytest.mark.asyncio
    async def test_tracks_and_adds_reactions_when_enabled(self, monkeypatch):
        """With the flag on, the reply is tracked and the palette is added."""
        monkeypatch.setenv("FEEDBACK_COLLECTION_ENABLED", "1")
        fake_collector = MagicMock()
        add_reactions = AsyncMock()
        monkeypatch.setattr("cogs.ai_core.logic.FEEDBACK_AVAILABLE", True)
        monkeypatch.setattr("cogs.ai_core.logic.feedback_collector", fake_collector)
        monkeypatch.setattr("cogs.ai_core.logic.add_feedback_reactions", add_reactions)

        sent = MagicMock()
        sent.id = 555
        await self._bare_manager()._maybe_track_feedback(sent, 456, "hello world")

        fake_collector.track_message.assert_called_once_with(555, 456, "hello world")
        add_reactions.assert_awaited_once_with(sent)

    @pytest.mark.asyncio
    async def test_noop_when_flag_unset(self, monkeypatch):
        """Default (flag unset) is a byte-for-byte no-op — nothing is tracked."""
        monkeypatch.delenv("FEEDBACK_COLLECTION_ENABLED", raising=False)
        fake_collector = MagicMock()
        add_reactions = AsyncMock()
        monkeypatch.setattr("cogs.ai_core.logic.FEEDBACK_AVAILABLE", True)
        monkeypatch.setattr("cogs.ai_core.logic.feedback_collector", fake_collector)
        monkeypatch.setattr("cogs.ai_core.logic.add_feedback_reactions", add_reactions)

        sent = MagicMock()
        sent.id = 555
        await self._bare_manager()._maybe_track_feedback(sent, 456, "hello world")

        fake_collector.track_message.assert_not_called()
        add_reactions.assert_not_awaited()


class TestOnRawReactionAddConsumer:
    """Tests for AI.on_raw_reaction_add (the consumer listener)."""

    @staticmethod
    def _listener(bot_user_id: int):
        """Bind the real listener to a minimal object exposing bot.user.id."""
        from cogs.ai_core.ai_cog import AI

        obj = SimpleNamespace(bot=SimpleNamespace(user=SimpleNamespace(id=bot_user_id)))
        return AI.on_raw_reaction_add.__get__(obj)

    @staticmethod
    def _payload(message_id: int, user_id: int, emoji: str):
        payload = MagicMock()
        payload.message_id = message_id
        payload.user_id = user_id
        payload.emoji = discord.PartialEmoji(name=emoji)
        return payload

    @pytest.mark.asyncio
    async def test_records_user_reaction_on_tracked_message(self, monkeypatch):
        """A real user reaction on a tracked message increments the stats."""
        from utils.monitoring.feedback import FeedbackCollector

        collector = FeedbackCollector()
        collector.track_message(1234, 5678)
        monkeypatch.setattr("cogs.ai_core.ai_cog.FEEDBACK_AVAILABLE", True)
        monkeypatch.setattr("cogs.ai_core.ai_cog.feedback_collector", collector)

        await self._listener(bot_user_id=999)(self._payload(1234, 42, "👍"))

        stats = collector.get_stats()
        assert stats.total_feedback == 1
        assert stats.positive_count == 1

    @pytest.mark.asyncio
    async def test_ignores_bots_own_reaction(self, monkeypatch):
        """The bot's own auto-added palette must not be recorded as feedback."""
        from utils.monitoring.feedback import FeedbackCollector

        collector = FeedbackCollector()
        collector.track_message(1234, 5678)
        monkeypatch.setattr("cogs.ai_core.ai_cog.FEEDBACK_AVAILABLE", True)
        monkeypatch.setattr("cogs.ai_core.ai_cog.feedback_collector", collector)

        await self._listener(bot_user_id=999)(self._payload(1234, 999, "👍"))

        assert collector.get_stats().total_feedback == 0

    @pytest.mark.asyncio
    async def test_noop_when_feedback_unavailable(self, monkeypatch):
        """FEEDBACK_AVAILABLE False → clean no-op, process_reaction never runs."""
        fake_collector = MagicMock()
        monkeypatch.setattr("cogs.ai_core.ai_cog.FEEDBACK_AVAILABLE", False)
        monkeypatch.setattr("cogs.ai_core.ai_cog.feedback_collector", fake_collector)

        await self._listener(bot_user_id=999)(self._payload(1234, 42, "👍"))

        fake_collector.process_reaction.assert_not_called()
