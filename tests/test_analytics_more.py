"""
Additional tests for AI Analytics module.
Tests log_interaction and calculate_quality_score methods.
"""

from unittest.mock import AsyncMock, patch

import pytest


class TestAIAnalyticsLogInteraction:
    """Tests for AIAnalytics.log_interaction method."""

    @pytest.mark.asyncio
    async def test_log_interaction_updates_total(self):
        """Test log_interaction updates total_interactions."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        initial = analytics._stats["total_interactions"]

        with patch.object(analytics, "_save_to_db", new_callable=AsyncMock):
            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="hello",
                output_text="hi there",
                response_time_ms=100.0,
            )

        assert analytics._stats["total_interactions"] == initial + 1

    @pytest.mark.asyncio
    async def test_log_interaction_updates_response_time(self):
        """Test log_interaction updates total_response_time_ms."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        initial = analytics._stats["total_response_time_ms"]

        with patch.object(analytics, "_save_to_db", new_callable=AsyncMock):
            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="hello",
                output_text="hi there",
                response_time_ms=150.0,
            )

        assert analytics._stats["total_response_time_ms"] == initial + 150.0

    @pytest.mark.asyncio
    async def test_log_interaction_counts_cache_hit(self):
        """Test log_interaction counts cache hits."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        initial = analytics._stats["cache_hits"]

        with patch.object(analytics, "_save_to_db", new_callable=AsyncMock):
            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="hello",
                output_text="cached response",
                response_time_ms=10.0,
                cache_hit=True,
            )

        assert analytics._stats["cache_hits"] == initial + 1

    @pytest.mark.asyncio
    async def test_log_interaction_counts_errors(self):
        """Test log_interaction counts errors."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        initial = analytics._stats["errors"]

        with patch.object(analytics, "_save_to_db", new_callable=AsyncMock):
            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="hello",
                output_text="",
                response_time_ms=500.0,
                error="API Error",
            )

        assert analytics._stats["errors"] == initial + 1

    @pytest.mark.asyncio
    async def test_log_interaction_updates_char_counts(self):
        """Test log_interaction updates character counts."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        initial_input = analytics._stats["total_input_chars"]
        initial_output = analytics._stats["total_output_chars"]

        with patch.object(analytics, "_save_to_db", new_callable=AsyncMock):
            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="hello world",  # 11 chars
                output_text="hi there!",  # 9 chars
                response_time_ms=100.0,
            )

        assert analytics._stats["total_input_chars"] == initial_input + 11
        assert analytics._stats["total_output_chars"] == initial_output + 9


class TestAIAnalyticsCalculateQualityScore:
    """Tests for AIAnalytics.calculate_quality_score method."""

    def test_calculate_quality_score_returns_quality(self):
        """Test calculate_quality_score returns ResponseQuality."""
        from cogs.ai_core.cache.analytics import AIAnalytics, ResponseQuality

        analytics = AIAnalytics()
        result = analytics.calculate_quality_score("Hello, how can I help?")

        assert isinstance(result, ResponseQuality)

    def test_calculate_quality_score_with_retry(self):
        """Test calculate_quality_score with retry count."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        result = analytics.calculate_quality_score("Response after retry", retry_count=2)

        assert result is not None

    def test_calculate_quality_score_with_edit(self):
        """Test calculate_quality_score with was_edited flag."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        result = analytics.calculate_quality_score("Edited response", was_edited=True)

        assert result is not None

    def test_calculate_quality_score_thumbs_up(self):
        """Test calculate_quality_score with thumbs up reaction."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        result = analytics.calculate_quality_score("Great response", user_reaction="👍")

        # Result should be a ResponseQuality object
        assert result is not None

    def test_calculate_quality_score_thumbs_down(self):
        """Test calculate_quality_score with thumbs down reaction."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        result = analytics.calculate_quality_score("Bad response", user_reaction="👎")

        # Result should be a ResponseQuality object
        assert result is not None

    def test_calculate_quality_score_guardrail(self):
        """Test calculate_quality_score with guardrail triggered."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        result = analytics.calculate_quality_score("Blocked response", guardrail_triggered=True)

        assert result is not None


class TestAIAnalyticsIntentCounts:
    """Tests for AIAnalytics intent counting."""

    @pytest.mark.asyncio
    async def test_log_interaction_counts_intent(self):
        """Test log_interaction counts intent."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        with patch.object(analytics, "_save_to_db", new_callable=AsyncMock):
            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="hello",
                output_text="hi",
                response_time_ms=100.0,
                intent="greeting",
            )

        assert analytics._stats["intent_counts"]["greeting"] > 0


class TestAIAnalyticsHourlyCounts:
    """Tests for AIAnalytics hourly counting."""

    @pytest.mark.asyncio
    async def test_log_interaction_tracks_hourly(self):
        """Test log_interaction tracks hourly counts."""
        from datetime import datetime

        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        hour_key = datetime.now().strftime("%Y-%m-%d-%H")

        with patch.object(analytics, "_save_to_db", new_callable=AsyncMock):
            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="hello",
                output_text="hi",
                response_time_ms=100.0,
            )

        assert hour_key in analytics._stats["hourly_counts"]


class TestAIAnalyticsNoCacheHit:
    """Tests for AIAnalytics without cache hit."""

    @pytest.mark.asyncio
    async def test_log_interaction_no_cache_hit(self):
        """Test log_interaction without cache hit doesn't increment."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        initial = analytics._stats["cache_hits"]

        with patch.object(analytics, "_save_to_db", new_callable=AsyncMock):
            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="hello",
                output_text="hi",
                response_time_ms=100.0,
                cache_hit=False,
            )

        assert analytics._stats["cache_hits"] == initial


class TestAIAnalyticsNoError:
    """Tests for AIAnalytics without error."""

    @pytest.mark.asyncio
    async def test_log_interaction_no_error(self):
        """Test log_interaction without error doesn't increment."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()
        initial = analytics._stats["errors"]

        with patch.object(analytics, "_save_to_db", new_callable=AsyncMock):
            await analytics.log_interaction(
                user_id=123,
                channel_id=456,
                guild_id=789,
                input_text="hello",
                output_text="hi",
                response_time_ms=100.0,
                error=None,
            )

        assert analytics._stats["errors"] == initial
