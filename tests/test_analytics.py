"""Tests for AI Analytics module."""

from datetime import datetime
from unittest.mock import patch

import pytest


class TestInteractionLog:
    """Tests for InteractionLog dataclass."""

    def test_create_interaction_log(self):
        """Test creating an interaction log entry."""
        from cogs.ai_core.cache.analytics import InteractionLog

        log = InteractionLog(
            user_id=123,
            channel_id=456,
            guild_id=789,
            input_length=50,
            output_length=200,
            response_time_ms=1500.0,
            intent="chat",
            model="gemini",
        )

        assert log.user_id == 123
        assert log.channel_id == 456
        assert log.guild_id == 789
        assert log.input_length == 50
        assert log.output_length == 200
        assert log.response_time_ms == 1500.0
        assert log.intent == "chat"
        assert log.model == "gemini"

    def test_default_values(self):
        """Test default values of InteractionLog."""
        from cogs.ai_core.cache.analytics import InteractionLog

        log = InteractionLog(
            user_id=1,
            channel_id=2,
            guild_id=None,
            input_length=10,
            output_length=20,
            response_time_ms=100.0,
            intent="test",
            model="test",
        )

        assert log.tool_calls == 0
        assert log.cache_hit is False
        assert log.error is None
        assert isinstance(log.timestamp, datetime)


class TestAnalyticsSummary:
    """Tests for AnalyticsSummary dataclass."""

    def test_create_summary(self):
        """Test creating an analytics summary."""
        from cogs.ai_core.cache.analytics import AnalyticsSummary

        summary = AnalyticsSummary(
            total_interactions=100,
            avg_response_time_ms=500.0,
            cache_hit_rate=0.25,
            top_intents=[("chat", 50), ("music", 30)],
            error_rate=0.05,
            interactions_per_hour=10.0,
            total_input_tokens=5000,
            total_output_tokens=15000,
        )

        assert summary.total_interactions == 100
        assert summary.avg_response_time_ms == 500.0
        assert summary.cache_hit_rate == 0.25
        assert len(summary.top_intents) == 2
        assert summary.error_rate == 0.05


class TestResponseQuality:
    """Tests for ResponseQuality dataclass."""

    def test_create_quality_score(self):
        """Test creating a quality score."""
        from cogs.ai_core.cache.analytics import ResponseQuality

        quality = ResponseQuality(score=0.85)

        assert quality.score == 0.85
        assert quality.retry_count == 0
        assert quality.was_edited is False
        assert quality.user_reaction is None
        assert quality.guardrail_triggered is False
        assert quality.response_length == 0
        assert isinstance(quality.factors, dict)

    def test_quality_with_factors(self):
        """Test quality score with factors."""
        from cogs.ai_core.cache.analytics import ResponseQuality

        quality = ResponseQuality(
            score=0.7,
            retry_count=2,
            was_edited=True,
            user_reaction="👍",
            guardrail_triggered=True,
            response_length=500,
            factors={"length": 0.8, "relevance": 0.6},
        )

        assert quality.score == 0.7
        assert quality.retry_count == 2
        assert quality.was_edited is True
        assert quality.user_reaction == "👍"
        assert quality.guardrail_triggered is True
        assert quality.factors["length"] == 0.8


class TestAIAnalytics:
    """Tests for AIAnalytics class."""

    def test_init(self):
        """Test AIAnalytics initialization."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        assert analytics._stats["total_interactions"] == 0
        assert analytics._stats["cache_hits"] == 0
        assert analytics._stats["errors"] == 0

    def test_chars_per_token_constant(self):
        """Test CHARS_PER_TOKEN constant."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        assert AIAnalytics.CHARS_PER_TOKEN == 4

    @pytest.mark.asyncio
    async def test_log_interaction(self):
        """Test logging an interaction."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        with patch("cogs.ai_core.cache.analytics.DB_AVAILABLE", False):
            analytics = AIAnalytics()

            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="Hello",
                output_text="Hi there!",
                response_time_ms=500.0,
                intent="greeting",
            )

            assert analytics._stats["total_interactions"] == 1
            assert analytics._stats["total_response_time_ms"] == 500.0
            assert analytics._stats["intent_counts"]["greeting"] == 1
            assert analytics._stats["total_input_chars"] == 5
            assert analytics._stats["total_output_chars"] == 9

    @pytest.mark.asyncio
    async def test_log_interaction_with_cache_hit(self):
        """Test logging a cached interaction."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        with patch("cogs.ai_core.cache.analytics.DB_AVAILABLE", False):
            analytics = AIAnalytics()

            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=None,
                input_text="test",
                output_text="response",
                response_time_ms=50.0,
                cache_hit=True,
            )

            assert analytics._stats["cache_hits"] == 1

    @pytest.mark.asyncio
    async def test_log_interaction_with_error(self):
        """Test logging an errored interaction."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        with patch("cogs.ai_core.cache.analytics.DB_AVAILABLE", False):
            analytics = AIAnalytics()

            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="test",
                output_text="",
                response_time_ms=100.0,
                error="API Error",
            )

            assert analytics._stats["errors"] == 1

    @pytest.mark.asyncio
    async def test_log_multiple_interactions(self):
        """Test logging multiple interactions."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        with patch("cogs.ai_core.cache.analytics.DB_AVAILABLE", False):
            analytics = AIAnalytics()

            for _i in range(5):
                await analytics.log_interaction(
                    user_id=123,
                    channel_id=456,
                    guild_id=789,
                    input_text="test",
                    output_text="response",
                    response_time_ms=100.0,
                    intent="chat",
                )

            assert analytics._stats["total_interactions"] == 5
            assert analytics._stats["intent_counts"]["chat"] == 5


class TestQualityScoreCalculation:
    """Tests for quality score calculation."""

    def test_calculate_quality_basic(self):
        """Test basic quality score calculation."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="This is a normal response to the user.",
        )

        assert 0.0 <= quality.score <= 1.0
        assert isinstance(quality.factors, dict)

    def test_quality_with_retry(self):
        """Test quality score with retry count."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Response after retries",
            retry_count=3,
        )

        # Retries should lower the score
        assert quality.retry_count == 3

    def test_quality_with_user_reaction_positive(self):
        """Test quality score with positive reaction."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Great response",
            user_reaction="👍",
        )

        assert quality.user_reaction == "👍"

    def test_quality_with_guardrail(self):
        """Test quality score with guardrail triggered."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Filtered response",
            guardrail_triggered=True,
        )

        assert quality.guardrail_triggered is True


class TestStatistics:
    """Tests for statistics methods."""

    def test_get_stats_initial(self):
        """Test getting initial stats."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        assert analytics._stats["total_interactions"] == 0
        assert analytics._stats["cache_hits"] == 0
        assert analytics._stats["errors"] == 0

    @pytest.mark.asyncio
    async def test_hourly_counts_tracked(self):
        """Test that hourly counts are tracked."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        with patch("cogs.ai_core.cache.analytics.DB_AVAILABLE", False):
            analytics = AIAnalytics()

            await analytics.log_interaction(
                user_id=1,
                channel_id=2,
                guild_id=3,
                input_text="test",
                output_text="response",
                response_time_ms=100.0,
            )

            # Should have at least one hourly entry
            assert len(analytics._stats["hourly_counts"]) > 0


class TestModuleImports:
    """Tests for module imports."""

    def test_import_interaction_log(self):
        """Test importing InteractionLog."""
        from cogs.ai_core.cache.analytics import InteractionLog

        assert InteractionLog is not None

    def test_import_analytics_summary(self):
        """Test importing AnalyticsSummary."""
        from cogs.ai_core.cache.analytics import AnalyticsSummary

        assert AnalyticsSummary is not None

    def test_import_response_quality(self):
        """Test importing ResponseQuality."""
        from cogs.ai_core.cache.analytics import ResponseQuality

        assert ResponseQuality is not None

    def test_import_ai_analytics(self):
        """Test importing AIAnalytics."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        assert AIAnalytics is not None
