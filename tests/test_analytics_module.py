"""
Tests for cogs/ai_core/cache/analytics.py module.
Tests AI interaction analytics and quality scoring.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ==================== TestDbAvailable ====================


class TestDbAvailable:
    """Test DB_AVAILABLE flag."""

    def test_db_available_flag_exists(self):
        """Test DB_AVAILABLE flag exists."""
        from cogs.ai_core.cache.analytics import DB_AVAILABLE

        assert isinstance(DB_AVAILABLE, bool)


# ==================== TestInteractionLog ====================


class TestInteractionLog:
    """Test InteractionLog dataclass."""

    def test_create_interaction_log(self):
        """Test creating InteractionLog."""
        from cogs.ai_core.cache.analytics import InteractionLog

        log = InteractionLog(
            user_id=123,
            channel_id=456,
            guild_id=789,
            input_length=100,
            output_length=200,
            response_time_ms=500.0,
            intent="greeting",
            model="gemini"
        )

        assert log.user_id == 123
        assert log.channel_id == 456
        assert log.guild_id == 789
        assert log.input_length == 100
        assert log.output_length == 200
        assert log.response_time_ms == 500.0
        assert log.intent == "greeting"
        assert log.model == "gemini"

    def test_interaction_log_defaults(self):
        """Test InteractionLog default values."""
        from cogs.ai_core.cache.analytics import InteractionLog

        log = InteractionLog(
            user_id=123,
            channel_id=456,
            guild_id=None,
            input_length=50,
            output_length=100,
            response_time_ms=200.0,
            intent="question",
            model="gemini"
        )

        assert log.tool_calls == 0
        assert log.cache_hit is False
        assert log.error is None
        assert isinstance(log.timestamp, datetime)

    def test_interaction_log_with_error(self):
        """Test InteractionLog with error."""
        from cogs.ai_core.cache.analytics import InteractionLog

        log = InteractionLog(
            user_id=123,
            channel_id=456,
            guild_id=789,
            input_length=50,
            output_length=0,
            response_time_ms=1000.0,
            intent="unknown",
            model="gemini",
            error="API rate limited"
        )

        assert log.error == "API rate limited"


# ==================== TestAnalyticsSummary ====================


class TestAnalyticsSummary:
    """Test AnalyticsSummary dataclass."""

    def test_create_analytics_summary(self):
        """Test creating AnalyticsSummary."""
        from cogs.ai_core.cache.analytics import AnalyticsSummary

        summary = AnalyticsSummary(
            total_interactions=100,
            avg_response_time_ms=250.0,
            cache_hit_rate=0.15,
            top_intents=[("greeting", 30), ("question", 25)],
            error_rate=0.05,
            interactions_per_hour=10.5,
            total_input_tokens=5000,
            total_output_tokens=10000
        )

        assert summary.total_interactions == 100
        assert summary.avg_response_time_ms == 250.0
        assert summary.cache_hit_rate == 0.15
        assert summary.error_rate == 0.05
        assert summary.total_input_tokens == 5000


# ==================== TestResponseQuality ====================


class TestResponseQuality:
    """Test ResponseQuality dataclass."""

    def test_create_response_quality(self):
        """Test creating ResponseQuality."""
        from cogs.ai_core.cache.analytics import ResponseQuality

        quality = ResponseQuality(score=0.85)

        assert quality.score == 0.85
        assert quality.retry_count == 0
        assert quality.was_edited is False
        assert quality.user_reaction is None
        assert quality.guardrail_triggered is False
        assert quality.response_length == 0
        assert quality.factors == {}

    def test_response_quality_with_all_fields(self):
        """Test ResponseQuality with all fields."""
        from cogs.ai_core.cache.analytics import ResponseQuality

        quality = ResponseQuality(
            score=0.7,
            retry_count=2,
            was_edited=True,
            user_reaction="👍",
            guardrail_triggered=True,
            response_length=500,
            factors={"retry_penalty": -0.2}
        )

        assert quality.score == 0.7
        assert quality.retry_count == 2
        assert quality.was_edited is True
        assert quality.user_reaction == "👍"
        assert quality.guardrail_triggered is True
        assert quality.response_length == 500


# ==================== TestAIAnalyticsInit ====================


class TestAIAnalyticsInit:
    """Test AIAnalytics initialization."""

    def test_init_creates_instance(self):
        """Test AIAnalytics creation."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        assert analytics is not None
        assert hasattr(analytics, 'logger')
        assert hasattr(analytics, '_stats')

    def test_init_stats_structure(self):
        """Test initial stats structure."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        assert analytics._stats["total_interactions"] == 0
        assert analytics._stats["total_response_time_ms"] == 0
        assert analytics._stats["cache_hits"] == 0
        assert analytics._stats["errors"] == 0
        assert "intent_counts" in analytics._stats
        assert "hourly_counts" in analytics._stats

    def test_init_has_start_time(self):
        """Test AIAnalytics has start time."""
        import time

        from cogs.ai_core.cache.analytics import AIAnalytics

        before = time.time()
        analytics = AIAnalytics()
        after = time.time()

        assert before <= analytics._start_time <= after


# ==================== TestLogInteraction ====================


@pytest.mark.asyncio
class TestLogInteraction:
    """Test log_interaction method."""

    async def test_log_interaction_basic(self):
        """Test logging a basic interaction."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        await analytics.log_interaction(
            user_id=123,
            channel_id=456,
            guild_id=789,
            input_text="Hello",
            output_text="Hi there!",
            response_time_ms=250.0,
            intent="greeting",
            model="gemini"
        )

        assert analytics._stats["total_interactions"] == 1
        assert analytics._stats["total_response_time_ms"] == 250.0
        assert analytics._stats["intent_counts"]["greeting"] == 1

    async def test_log_interaction_with_cache_hit(self):
        """Test logging interaction with cache hit."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        await analytics.log_interaction(
            user_id=123,
            channel_id=456,
            guild_id=789,
            input_text="Hello",
            output_text="Hi!",
            response_time_ms=10.0,
            intent="greeting",
            model="gemini",
            cache_hit=True
        )

        assert analytics._stats["cache_hits"] == 1

    async def test_log_interaction_with_error(self):
        """Test logging interaction with error."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        await analytics.log_interaction(
            user_id=123,
            channel_id=456,
            guild_id=789,
            input_text="Hello",
            output_text="",
            response_time_ms=5000.0,
            intent="unknown",
            model="gemini",
            error="Rate limited"
        )

        assert analytics._stats["errors"] == 1

    async def test_log_interaction_tracks_chars(self):
        """Test logging interaction tracks character counts."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        await analytics.log_interaction(
            user_id=123,
            channel_id=456,
            guild_id=789,
            input_text="Hello World",  # 11 chars
            output_text="Hi there!",     # 9 chars
            response_time_ms=100.0,
            intent="greeting",
            model="gemini"
        )

        assert analytics._stats["total_input_chars"] == 11
        assert analytics._stats["total_output_chars"] == 9


# ==================== TestCalculateQualityScore ====================


class TestCalculateQualityScore:
    """Test calculate_quality_score method."""

    def test_quality_score_perfect(self):
        """Test perfect quality score."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="This is a well-formed response with good content.",
            retry_count=0,
            was_edited=False,
            user_reaction=None,
            guardrail_triggered=False
        )

        assert quality.score == 1.0

    def test_quality_score_with_retry(self):
        """Test quality score with retries."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Response after retry.",
            retry_count=2,
            was_edited=False,
            user_reaction=None,
            guardrail_triggered=False
        )

        # -0.2 for 2 retries
        assert quality.score < 1.0
        assert "retry_penalty" in quality.factors

    def test_quality_score_with_edit(self):
        """Test quality score with edit."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Edited response content here.",
            retry_count=0,
            was_edited=True,
            user_reaction=None,
            guardrail_triggered=False
        )

        # -0.2 for edit
        assert quality.score == 0.8
        assert quality.factors["edit_penalty"] == -0.2

    def test_quality_score_positive_reaction(self):
        """Test quality score with positive reaction."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Great response that user liked.",
            retry_count=0,
            was_edited=False,
            user_reaction="👍",
            guardrail_triggered=False
        )

        # Clamped to 1.0 even with +0.1 bonus
        assert quality.score == 1.0
        assert quality.factors["positive_reaction"] == 0.1

    def test_quality_score_negative_reaction(self):
        """Test quality score with negative reaction."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Response that user disliked.",
            retry_count=0,
            was_edited=False,
            user_reaction="👎",
            guardrail_triggered=False
        )

        # -0.3 for negative reaction
        assert quality.score == 0.7
        assert quality.factors["negative_reaction"] == -0.3

    def test_quality_score_guardrail(self):
        """Test quality score with guardrail triggered."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Response that triggered guardrail.",
            retry_count=0,
            was_edited=False,
            user_reaction=None,
            guardrail_triggered=True
        )

        # -0.2 for guardrail
        assert quality.score == 0.8
        assert quality.factors["guardrail_penalty"] == -0.2

    def test_quality_score_short_response(self):
        """Test quality score with very short response."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Short",  # < 20 chars
            retry_count=0,
            was_edited=False,
            user_reaction=None,
            guardrail_triggered=False
        )

        # -0.1 for short response
        assert quality.score == 0.9
        assert quality.factors["short_response"] == -0.1

    def test_quality_score_clamped_minimum(self):
        """Test quality score is clamped to minimum 0.0."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Bad",  # short
            retry_count=3,   # max penalty -0.3
            was_edited=True,  # -0.2
            user_reaction="👎",  # -0.3
            guardrail_triggered=True  # -0.2
        )

        # Total penalties exceed 1.0, should be clamped to 0.0
        assert quality.score == 0.0


# ==================== TestLogResponseQuality ====================


class TestLogResponseQuality:
    """Test log_response_quality method."""

    def test_log_response_quality_basic(self):
        """Test logging response quality."""
        from cogs.ai_core.cache.analytics import AIAnalytics, ResponseQuality

        analytics = AIAnalytics()
        quality = ResponseQuality(score=0.9)

        analytics.log_response_quality(quality)

        assert "quality_scores" in analytics._stats
        assert len(analytics._stats["quality_scores"]) == 1
        assert analytics._stats["quality_sum"] == 0.9
        assert analytics._stats["quality_count"] == 1

    def test_log_response_quality_tracks_reactions(self):
        """Test logging response quality tracks reactions."""
        from cogs.ai_core.cache.analytics import AIAnalytics, ResponseQuality

        analytics = AIAnalytics()

        positive = ResponseQuality(score=0.9, user_reaction="👍")
        negative = ResponseQuality(score=0.5, user_reaction="👎")

        analytics.log_response_quality(positive)
        analytics.log_response_quality(negative)

        assert analytics._stats["positive_reactions"] == 1
        assert analytics._stats["negative_reactions"] == 1


# ==================== TestCharsPerToken ====================


class TestCharsPerToken:
    """Test CHARS_PER_TOKEN constant."""

    def test_chars_per_token_constant(self):
        """Test CHARS_PER_TOKEN constant exists."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        assert AIAnalytics.CHARS_PER_TOKEN == 4


# ==================== TestModuleImports ====================


class TestModuleImports:
    """Test module imports."""

    def test_import_analytics(self):
        """Test importing analytics module."""
        import cogs.ai_core.cache.analytics

        assert cogs.ai_core.cache.analytics is not None

    def test_import_ai_analytics(self):
        """Test importing AIAnalytics class."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        assert AIAnalytics is not None

    def test_import_interaction_log(self):
        """Test importing InteractionLog dataclass."""
        from cogs.ai_core.cache.analytics import InteractionLog

        assert InteractionLog is not None

    def test_import_analytics_summary(self):
        """Test importing AnalyticsSummary dataclass."""
        from cogs.ai_core.cache.analytics import AnalyticsSummary

        assert AnalyticsSummary is not None

    def test_import_response_quality(self):
        """Test importing ResponseQuality dataclass."""
        from cogs.ai_core.cache.analytics import ResponseQuality

        assert ResponseQuality is not None


# ==================== TestIntentCounts ====================


class TestIntentCounts:
    """Test intent counting."""

    @pytest.mark.asyncio
    async def test_multiple_intents_tracked(self):
        """Test multiple intents are tracked."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        await analytics.log_interaction(
            user_id=1, channel_id=1, guild_id=1,
            input_text="Hi", output_text="Hello",
            response_time_ms=100.0, intent="greeting", model="gemini"
        )

        await analytics.log_interaction(
            user_id=1, channel_id=1, guild_id=1,
            input_text="What's 2+2?", output_text="4",
            response_time_ms=150.0, intent="question", model="gemini"
        )

        await analytics.log_interaction(
            user_id=1, channel_id=1, guild_id=1,
            input_text="Hello again", output_text="Hi again!",
            response_time_ms=120.0, intent="greeting", model="gemini"
        )

        assert analytics._stats["intent_counts"]["greeting"] == 2
        assert analytics._stats["intent_counts"]["question"] == 1


# ==================== TestHourlyCounts ====================


class TestHourlyCounts:
    """Test hourly counting."""

    @pytest.mark.asyncio
    async def test_hourly_counts_tracked(self):
        """Test hourly counts are tracked."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        await analytics.log_interaction(
            user_id=1, channel_id=1, guild_id=1,
            input_text="Test", output_text="Response",
            response_time_ms=100.0, intent="test", model="gemini"
        )

        # Should have at least one hourly entry
        assert len(analytics._stats["hourly_counts"]) >= 1


# ==================== TestConfusionReaction ====================


class TestConfusionReaction:
    """Test confusion reaction scoring."""

    def test_quality_score_confusion_reaction(self):
        """Test quality score with confusion reaction."""
        from cogs.ai_core.cache.analytics import AIAnalytics

        analytics = AIAnalytics()

        quality = analytics.calculate_quality_score(
            response="Response that confused user.",
            retry_count=0,
            was_edited=False,
            user_reaction="❓",
            guardrail_triggered=False
        )

        # -0.1 for confusion reaction
        assert quality.score == 0.9
        assert quality.factors["confusion_reaction"] == -0.1
