"""
Extended tests for AI Analytics module.
Tests dataclasses and AIAnalytics class.
"""

from datetime import datetime

import pytest


class TestInteractionLog:
    """Tests for InteractionLog dataclass."""

    def test_interaction_log_basic(self):
        """Test InteractionLog with basic values."""
        try:
            from cogs.ai_core.cache.analytics import InteractionLog
        except ImportError:
            pytest.skip("analytics not available")
            return

        log = InteractionLog(
            user_id=123,
            channel_id=456,
            guild_id=789,
            input_length=100,
            output_length=200,
            response_time_ms=150.5,
            intent="question",
            model="gemini-1.5-flash"
        )

        assert log.user_id == 123
        assert log.channel_id == 456
        assert log.guild_id == 789
        assert log.input_length == 100
        assert log.output_length == 200
        assert log.response_time_ms == 150.5
        assert log.intent == "question"
        assert log.model == "gemini-1.5-flash"

    def test_interaction_log_defaults(self):
        """Test InteractionLog default values."""
        try:
            from cogs.ai_core.cache.analytics import InteractionLog
        except ImportError:
            pytest.skip("analytics not available")
            return

        log = InteractionLog(
            user_id=1,
            channel_id=2,
            guild_id=3,
            input_length=50,
            output_length=100,
            response_time_ms=100.0,
            intent="chat",
            model="test"
        )

        assert log.tool_calls == 0
        assert log.cache_hit is False
        assert log.error is None
        assert isinstance(log.timestamp, datetime)

    def test_interaction_log_with_error(self):
        """Test InteractionLog with error."""
        try:
            from cogs.ai_core.cache.analytics import InteractionLog
        except ImportError:
            pytest.skip("analytics not available")
            return

        log = InteractionLog(
            user_id=1,
            channel_id=2,
            guild_id=3,
            input_length=50,
            output_length=0,
            response_time_ms=500.0,
            intent="chat",
            model="test",
            error="Timeout error"
        )

        assert log.error == "Timeout error"


class TestAnalyticsSummary:
    """Tests for AnalyticsSummary dataclass."""

    def test_analytics_summary_basic(self):
        """Test AnalyticsSummary with basic values."""
        try:
            from cogs.ai_core.cache.analytics import AnalyticsSummary
        except ImportError:
            pytest.skip("analytics not available")
            return

        summary = AnalyticsSummary(
            total_interactions=1000,
            avg_response_time_ms=150.0,
            cache_hit_rate=0.25,
            top_intents=[("chat", 500), ("question", 300)],
            error_rate=0.02,
            interactions_per_hour=50.0,
            total_input_tokens=10000,
            total_output_tokens=20000
        )

        assert summary.total_interactions == 1000
        assert summary.avg_response_time_ms == 150.0
        assert summary.cache_hit_rate == 0.25
        assert summary.error_rate == 0.02


class TestResponseQuality:
    """Tests for ResponseQuality dataclass."""

    def test_response_quality_defaults(self):
        """Test ResponseQuality default values."""
        try:
            from cogs.ai_core.cache.analytics import ResponseQuality
        except ImportError:
            pytest.skip("analytics not available")
            return

        quality = ResponseQuality(score=0.8)

        assert quality.score == 0.8
        assert quality.retry_count == 0
        assert quality.was_edited is False
        assert quality.user_reaction is None
        assert quality.guardrail_triggered is False
        assert quality.response_length == 0
        assert quality.factors == {}

    def test_response_quality_with_values(self):
        """Test ResponseQuality with custom values."""
        try:
            from cogs.ai_core.cache.analytics import ResponseQuality
        except ImportError:
            pytest.skip("analytics not available")
            return

        quality = ResponseQuality(
            score=0.9,
            retry_count=1,
            was_edited=True,
            user_reaction="👍",
            guardrail_triggered=False,
            response_length=500,
            factors={"relevance": 0.95, "fluency": 0.85}
        )

        assert quality.score == 0.9
        assert quality.retry_count == 1
        assert quality.user_reaction == "👍"
        assert "relevance" in quality.factors


class TestAIAnalyticsInit:
    """Tests for AIAnalytics initialization."""

    def test_ai_analytics_init(self):
        """Test AIAnalytics initializes correctly."""
        try:
            from cogs.ai_core.cache.analytics import AIAnalytics
        except ImportError:
            pytest.skip("analytics not available")
            return

        analytics = AIAnalytics()

        assert hasattr(analytics, 'logger')
        assert hasattr(analytics, '_stats')
        assert hasattr(analytics, '_start_time')

    def test_ai_analytics_initial_stats(self):
        """Test AIAnalytics initial stats are zero."""
        try:
            from cogs.ai_core.cache.analytics import AIAnalytics
        except ImportError:
            pytest.skip("analytics not available")
            return

        analytics = AIAnalytics()

        assert analytics._stats["total_interactions"] == 0
        assert analytics._stats["total_response_time_ms"] == 0
        assert analytics._stats["cache_hits"] == 0
        assert analytics._stats["errors"] == 0


class TestAIAnalyticsConstants:
    """Tests for AIAnalytics constants."""

    def test_chars_per_token_constant(self):
        """Test CHARS_PER_TOKEN constant."""
        try:
            from cogs.ai_core.cache.analytics import AIAnalytics
        except ImportError:
            pytest.skip("analytics not available")
            return

        assert AIAnalytics.CHARS_PER_TOKEN == 4


class TestDatabaseAvailable:
    """Tests for DB_AVAILABLE flag."""

    def test_db_available_defined(self):
        """Test DB_AVAILABLE is defined."""
        try:
            from cogs.ai_core.cache.analytics import DB_AVAILABLE
        except ImportError:
            pytest.skip("analytics not available")
            return

        assert isinstance(DB_AVAILABLE, bool)


class TestModuleDocstring:
    """Tests for module documentation."""

    def test_module_has_docstring(self):
        """Test analytics module has docstring."""
        try:
            from cogs.ai_core.cache import analytics
        except ImportError:
            pytest.skip("analytics not available")
            return

        assert analytics.__doc__ is not None


class TestInteractionLogTimestamp:
    """Tests for InteractionLog timestamp handling."""

    def test_timestamp_auto_set(self):
        """Test timestamp is automatically set."""
        try:
            from cogs.ai_core.cache.analytics import InteractionLog
        except ImportError:
            pytest.skip("analytics not available")
            return

        before = datetime.now()
        log = InteractionLog(
            user_id=1, channel_id=2, guild_id=3,
            input_length=10, output_length=20,
            response_time_ms=50.0, intent="test", model="test"
        )
        after = datetime.now()

        assert before <= log.timestamp <= after

    def test_timestamp_custom(self):
        """Test timestamp can be set manually."""
        try:
            from cogs.ai_core.cache.analytics import InteractionLog
        except ImportError:
            pytest.skip("analytics not available")
            return

        custom_time = datetime(2024, 1, 1, 12, 0, 0)
        log = InteractionLog(
            user_id=1, channel_id=2, guild_id=3,
            input_length=10, output_length=20,
            response_time_ms=50.0, intent="test", model="test",
            timestamp=custom_time
        )

        assert log.timestamp == custom_time


class TestResponseQualityReactions:
    """Tests for ResponseQuality user reactions."""

    def test_reaction_thumbs_up(self):
        """Test thumbs up reaction."""
        try:
            from cogs.ai_core.cache.analytics import ResponseQuality
        except ImportError:
            pytest.skip("analytics not available")
            return

        quality = ResponseQuality(score=0.9, user_reaction="👍")
        assert quality.user_reaction == "👍"

    def test_reaction_thumbs_down(self):
        """Test thumbs down reaction."""
        try:
            from cogs.ai_core.cache.analytics import ResponseQuality
        except ImportError:
            pytest.skip("analytics not available")
            return

        quality = ResponseQuality(score=0.5, user_reaction="👎")
        assert quality.user_reaction == "👎"


class TestAnalyticsSummaryTopIntents:
    """Tests for AnalyticsSummary top_intents."""

    def test_top_intents_structure(self):
        """Test top_intents is list of tuples."""
        try:
            from cogs.ai_core.cache.analytics import AnalyticsSummary
        except ImportError:
            pytest.skip("analytics not available")
            return

        summary = AnalyticsSummary(
            total_interactions=100,
            avg_response_time_ms=100.0,
            cache_hit_rate=0.1,
            top_intents=[("chat", 50), ("question", 30), ("command", 20)],
            error_rate=0.01,
            interactions_per_hour=10.0,
            total_input_tokens=1000,
            total_output_tokens=2000
        )

        assert isinstance(summary.top_intents, list)
        assert len(summary.top_intents) == 3
        assert summary.top_intents[0] == ("chat", 50)
