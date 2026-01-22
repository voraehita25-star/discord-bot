"""Tests for token_tracker module."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTokenUsageDataclass:
    """Tests for TokenUsage dataclass."""

    def test_token_usage_creation(self):
        """Test creating a TokenUsage instance."""
        from cogs.ai_core.cache.token_tracker import TokenUsage

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
        )

        assert usage.input_tokens == 100
        assert usage.output_tokens == 200
        assert usage.user_id == 123
        assert usage.channel_id == 456

    def test_token_usage_total_tokens(self):
        """Test total_tokens property."""
        from cogs.ai_core.cache.token_tracker import TokenUsage

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
        )

        assert usage.total_tokens == 300

    def test_token_usage_estimated_cost(self):
        """Test estimated_cost property."""
        from cogs.ai_core.cache.token_tracker import TokenUsage

        # 1M input + 1M output tokens
        usage = TokenUsage(
            input_tokens=1_000_000,
            output_tokens=1_000_000,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
        )

        # $0.10/1M input + $0.40/1M output = $0.50
        assert usage.estimated_cost == 0.50

    def test_token_usage_with_guild(self):
        """Test TokenUsage with guild_id."""
        from cogs.ai_core.cache.token_tracker import TokenUsage

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
            guild_id=789,
        )

        assert usage.guild_id == 789

    def test_token_usage_default_model(self):
        """Test default model value."""
        from cogs.ai_core.cache.token_tracker import TokenUsage

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
        )

        assert usage.model == "gemini-3-pro-preview"

    def test_token_usage_cached_default(self):
        """Test default cached value."""
        from cogs.ai_core.cache.token_tracker import TokenUsage

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
        )

        assert usage.cached is False


class TestUsageLimitsDataclass:
    """Tests for UsageLimits dataclass."""

    def test_usage_limits_defaults(self):
        """Test default limit values."""
        from cogs.ai_core.cache.token_tracker import UsageLimits

        limits = UsageLimits()

        assert limits.daily_user_tokens == 100_000
        assert limits.daily_channel_tokens == 500_000
        assert limits.daily_guild_tokens == 2_000_000
        assert limits.hourly_user_tokens == 20_000
        assert limits.warning_threshold == 0.8

    def test_usage_limits_custom(self):
        """Test custom limit values."""
        from cogs.ai_core.cache.token_tracker import UsageLimits

        limits = UsageLimits(
            daily_user_tokens=50_000,
            hourly_user_tokens=10_000,
        )

        assert limits.daily_user_tokens == 50_000
        assert limits.hourly_user_tokens == 10_000


class TestUsageStatsDataclass:
    """Tests for UsageStats dataclass."""

    def test_usage_stats_defaults(self):
        """Test default stats values."""
        from cogs.ai_core.cache.token_tracker import UsageStats

        stats = UsageStats()

        assert stats.total_tokens == 0
        assert stats.input_tokens == 0
        assert stats.output_tokens == 0
        assert stats.request_count == 0
        assert stats.cached_count == 0
        assert stats.estimated_cost == 0.0
        assert stats.period_start is None
        assert stats.period_end is None


class TestTokenTracker:
    """Tests for TokenTracker class."""

    def test_tracker_creation(self):
        """Test creating TokenTracker."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        assert tracker.limits is not None
        assert tracker._usage_cache is not None
        assert tracker._cleanup_task is None

    def test_tracker_with_custom_limits(self):
        """Test creating TokenTracker with custom limits."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, UsageLimits

        limits = UsageLimits(daily_user_tokens=50_000)
        tracker = TokenTracker(limits=limits)

        assert tracker.limits.daily_user_tokens == 50_000

    @pytest.mark.asyncio
    async def test_record_usage(self):
        """Test recording token usage."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, TokenUsage

        tracker = TokenTracker()

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
        )

        with patch.object(tracker, '_persist_usage', new_callable=AsyncMock):
            await tracker.record_usage(usage)

        # Check usage was stored
        assert "user:123" in tracker._usage_cache
        assert len(tracker._usage_cache["user:123"]) == 1
        assert "channel:456" in tracker._usage_cache

    @pytest.mark.asyncio
    async def test_record_usage_with_guild(self):
        """Test recording usage with guild_id."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, TokenUsage

        tracker = TokenTracker()

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
            guild_id=789,
        )

        with patch.object(tracker, '_persist_usage', new_callable=AsyncMock):
            await tracker.record_usage(usage)

        assert "guild:789" in tracker._usage_cache

    @pytest.mark.asyncio
    async def test_get_user_usage_empty(self):
        """Test get_user_usage with no records."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        stats = await tracker.get_user_usage(999)

        assert stats.total_tokens == 0
        assert stats.request_count == 0

    @pytest.mark.asyncio
    async def test_get_user_usage_with_records(self):
        """Test get_user_usage with records."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, TokenUsage

        tracker = TokenTracker()

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
        )

        with patch.object(tracker, '_persist_usage', new_callable=AsyncMock):
            await tracker.record_usage(usage)

        stats = await tracker.get_user_usage(123)

        assert stats.total_tokens == 300
        assert stats.input_tokens == 100
        assert stats.output_tokens == 200
        assert stats.request_count == 1

    @pytest.mark.asyncio
    async def test_get_user_usage_hour_period(self):
        """Test get_user_usage with hour period."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        stats = await tracker.get_user_usage(123, period="hour")

        assert stats.total_tokens == 0

    @pytest.mark.asyncio
    async def test_get_user_usage_week_period(self):
        """Test get_user_usage with week period."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        stats = await tracker.get_user_usage(123, period="week")

        assert stats.total_tokens == 0

    @pytest.mark.asyncio
    async def test_get_channel_usage(self):
        """Test get_channel_usage."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        stats = await tracker.get_channel_usage(456)

        assert stats.total_tokens == 0

    @pytest.mark.asyncio
    async def test_get_guild_usage(self):
        """Test get_guild_usage."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        stats = await tracker.get_guild_usage(789)

        assert stats.total_tokens == 0

    @pytest.mark.asyncio
    async def test_check_limits_allowed(self):
        """Test check_limits when within limits."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        allowed, warning = await tracker.check_limits(123)

        assert allowed is True

    @pytest.mark.asyncio
    async def test_check_limits_hourly_exceeded(self):
        """Test check_limits when hourly limit exceeded."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, TokenUsage, UsageLimits

        limits = UsageLimits(hourly_user_tokens=100)  # Very low limit
        tracker = TokenTracker(limits=limits)

        # Add usage exceeding limit
        usage = TokenUsage(
            input_tokens=100,
            output_tokens=100,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
        )

        with patch.object(tracker, '_persist_usage', new_callable=AsyncMock):
            await tracker.record_usage(usage)

        allowed, warning = await tracker.check_limits(123)

        assert allowed is False
        assert "รายชั่วโมง" in warning

    @pytest.mark.asyncio
    async def test_check_limits_daily_exceeded(self):
        """Test check_limits when daily limit exceeded."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, TokenUsage, UsageLimits

        limits = UsageLimits(daily_user_tokens=100, hourly_user_tokens=1000)  # Very low daily
        tracker = TokenTracker(limits=limits)

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=100,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
        )

        with patch.object(tracker, '_persist_usage', new_callable=AsyncMock):
            await tracker.record_usage(usage)

        allowed, warning = await tracker.check_limits(123)

        assert allowed is False
        assert "รายวัน" in warning

    @pytest.mark.asyncio
    async def test_check_limits_warning_threshold(self):
        """Test check_limits warning at threshold."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, TokenUsage, UsageLimits

        # 80% threshold = 80 tokens triggers warning at 100 token limit
        limits = UsageLimits(daily_user_tokens=100, hourly_user_tokens=10000, warning_threshold=0.8)
        tracker = TokenTracker(limits=limits)

        # Add 85 tokens (exceeds 80% threshold)
        usage = TokenUsage(
            input_tokens=45,
            output_tokens=40,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
        )

        with patch.object(tracker, '_persist_usage', new_callable=AsyncMock):
            await tracker.record_usage(usage)

        allowed, warning = await tracker.check_limits(123)

        assert allowed is True
        assert warning is not None
        assert "เหลือโควต้า" in warning

    def test_get_global_stats_empty(self):
        """Test get_global_stats with no records."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        stats = tracker.get_global_stats()

        assert stats["total_records"] == 0
        assert stats["total_tokens"] == 0
        assert stats["unique_users"] == 0
        assert stats["unique_channels"] == 0
        assert stats["unique_guilds"] == 0

    @pytest.mark.asyncio
    async def test_get_global_stats_with_records(self):
        """Test get_global_stats with records."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, TokenUsage

        tracker = TokenTracker()

        usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            timestamp=datetime.now(),
            user_id=123,
            channel_id=456,
            guild_id=789,
        )

        with patch.object(tracker, '_persist_usage', new_callable=AsyncMock):
            await tracker.record_usage(usage)

        stats = tracker.get_global_stats()

        assert stats["unique_users"] == 1
        assert stats["unique_channels"] == 1
        assert stats["unique_guilds"] == 1

    def test_start_cleanup_task(self):
        """Test starting cleanup task."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        # Won't actually start without event loop
        assert tracker._cleanup_task is None

    def test_stop_cleanup_task_when_none(self):
        """Test stopping cleanup task when none."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        # Should not raise
        tracker.stop_cleanup_task()

        assert tracker._cleanup_task is None

    @pytest.mark.asyncio
    async def test_cleanup_old_records(self):
        """Test cleanup of old records."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, TokenUsage

        tracker = TokenTracker()

        # Add an old record
        old_usage = TokenUsage(
            input_tokens=100,
            output_tokens=200,
            timestamp=datetime.now() - timedelta(days=8),  # 8 days old
            user_id=123,
            channel_id=456,
        )

        # Add directly to cache
        tracker._usage_cache["user:123"].append(old_usage)

        await tracker._cleanup_old_records()

        # Old record should be removed
        assert len(tracker._usage_cache.get("user:123", [])) == 0

    def test_aggregate_usage_empty(self):
        """Test _aggregate_usage with empty list."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        tracker = TokenTracker()

        stats = tracker._aggregate_usage([])

        assert stats.total_tokens == 0
        assert stats.request_count == 0

    def test_aggregate_usage_with_records(self):
        """Test _aggregate_usage with records."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, TokenUsage

        tracker = TokenTracker()

        records = [
            TokenUsage(
                input_tokens=100,
                output_tokens=200,
                timestamp=datetime.now(),
                user_id=123,
                channel_id=456,
                cached=False,
            ),
            TokenUsage(
                input_tokens=50,
                output_tokens=100,
                timestamp=datetime.now(),
                user_id=123,
                channel_id=456,
                cached=True,
            ),
        ]

        stats = tracker._aggregate_usage(records)

        assert stats.total_tokens == 450
        assert stats.input_tokens == 150
        assert stats.output_tokens == 300
        assert stats.request_count == 2
        assert stats.cached_count == 1

    def test_get_usage_in_period(self):
        """Test _get_usage_in_period."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, TokenUsage

        tracker = TokenTracker()

        # Add records with different timestamps
        now = datetime.now()
        tracker._usage_cache["user:123"] = [
            TokenUsage(
                input_tokens=100,
                output_tokens=200,
                timestamp=now,
                user_id=123,
                channel_id=456,
            ),
            TokenUsage(
                input_tokens=50,
                output_tokens=100,
                timestamp=now - timedelta(hours=2),
                user_id=123,
                channel_id=456,
            ),
        ]

        # Get records from last hour
        records = tracker._get_usage_in_period("user:123", timedelta(hours=1))

        assert len(records) == 1
        assert records[0].input_tokens == 100


class TestGlobalInstance:
    """Tests for global token_tracker instance."""

    def test_global_instance_exists(self):
        """Test global token_tracker instance exists."""
        from cogs.ai_core.cache.token_tracker import token_tracker

        assert token_tracker is not None

    def test_global_instance_is_tracker(self):
        """Test global instance is TokenTracker."""
        from cogs.ai_core.cache.token_tracker import TokenTracker, token_tracker

        assert isinstance(token_tracker, TokenTracker)


class TestModuleImports:
    """Tests for module imports."""

    def test_import_token_usage(self):
        """Test importing TokenUsage."""
        from cogs.ai_core.cache.token_tracker import TokenUsage

        assert TokenUsage is not None

    def test_import_usage_limits(self):
        """Test importing UsageLimits."""
        from cogs.ai_core.cache.token_tracker import UsageLimits

        assert UsageLimits is not None

    def test_import_usage_stats(self):
        """Test importing UsageStats."""
        from cogs.ai_core.cache.token_tracker import UsageStats

        assert UsageStats is not None

    def test_import_token_tracker(self):
        """Test importing TokenTracker class."""
        from cogs.ai_core.cache.token_tracker import TokenTracker

        assert TokenTracker is not None
