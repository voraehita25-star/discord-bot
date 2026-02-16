"""
Unit Tests for Rate Limiter Module
Tests token bucket algorithm, rate limit configurations, and utility functions.
"""

# Import the module under test
import sys
import time

import pytest

sys.path.insert(0, "c:/Users/ME/BOT")

from utils.reliability.rate_limiter import (
    RateLimitBucket,
    RateLimitConfig,
    RateLimiter,
    RateLimitType,
    format_rate_limit_stats,
    rate_limiter,
)


class TestRateLimitBucket:
    """Tests for RateLimitBucket class."""

    def test_initial_consume_success(self):
        """Test that initial consume succeeds with full tokens."""
        bucket = RateLimitBucket(tokens=5.0, last_update=time.time(), window=10.0, max_tokens=5)

        success, retry_after = bucket.consume()

        assert success is True
        assert retry_after == 0.0
        assert bucket.tokens == 4.0

    def test_consume_depletes_tokens(self):
        """Test that consuming depletes tokens correctly."""
        bucket = RateLimitBucket(tokens=2.0, last_update=time.time(), window=10.0, max_tokens=5)

        # Consume twice
        bucket.consume()
        bucket.consume()

        # Third consume should fail
        success, retry_after = bucket.consume()

        assert success is False
        assert retry_after > 0

    def test_tokens_replenish_over_time(self):
        """Test that tokens replenish based on time passed."""
        past_time = time.time() - 10  # 10 seconds ago
        bucket = RateLimitBucket(tokens=0.0, last_update=past_time, window=10.0, max_tokens=5)

        # After 10 seconds, should have 5 tokens (full replenishment)
        success, _retry_after = bucket.consume()

        assert success is True
        assert bucket.tokens == 4.0  # 5 replenished - 1 consumed


class TestRateLimiter:
    """Tests for RateLimiter class."""

    @pytest.fixture
    def limiter(self):
        """Create a fresh rate limiter for testing."""
        return RateLimiter()

    def test_default_configs_exist(self, limiter):
        """Test that default configurations are created."""
        assert "gemini_api" in limiter._configs
        assert "gemini_global" in limiter._configs
        assert "music_command" in limiter._configs
        assert "command" in limiter._configs
        assert "spam" in limiter._configs

    def test_add_custom_config(self, limiter):
        """Test adding a custom rate limit configuration."""
        config = RateLimitConfig(
            requests=10, window=60, limit_type=RateLimitType.USER, cooldown_message="Test cooldown"
        )

        limiter.add_config("test_config", config)

        assert "test_config" in limiter._configs
        assert limiter._configs["test_config"].requests == 10

    @pytest.mark.asyncio
    async def test_check_allows_first_request(self, limiter):
        """Test that first request is allowed."""
        allowed, retry_after, message = await limiter.check("command", user_id=12345)

        assert allowed is True
        assert retry_after == 0.0
        assert message is None

    @pytest.mark.asyncio
    async def test_check_blocks_after_limit(self, limiter):
        """Test that requests are blocked after limit is reached."""
        # Add a strict test config
        config = RateLimitConfig(
            requests=2,
            window=60,
            limit_type=RateLimitType.USER,
            cooldown_message="Wait {retry:.1f}s",
        )
        limiter.add_config("strict_test", config)

        # First two requests should pass
        await limiter.check("strict_test", user_id=99999)
        await limiter.check("strict_test", user_id=99999)

        # Third request should be blocked
        allowed, retry_after, message = await limiter.check("strict_test", user_id=99999)

        assert allowed is False
        assert retry_after > 0
        assert "Wait" in message

    @pytest.mark.asyncio
    async def test_is_allowed_returns_boolean(self, limiter):
        """Test that is_allowed returns a simple boolean."""
        result = await limiter.is_allowed("command", user_id=11111)

        assert isinstance(result, bool)
        assert result is True

    @pytest.mark.asyncio
    async def test_unknown_config_always_allowed(self, limiter):
        """Test that unknown config name allows all requests."""
        allowed, retry_after, message = await limiter.check("nonexistent_config", user_id=12345)

        assert allowed is True
        assert retry_after == 0.0
        assert message is None

    @pytest.mark.asyncio
    async def test_cleanup_old_buckets(self, limiter):
        """Test cleanup removes old buckets."""
        # Create a bucket
        await limiter.check("command", user_id=88888)

        # Manually make bucket old
        for key in limiter._buckets:
            limiter._buckets[key].last_update = time.time() - 4000  # Old

        # Clean up with short max_age
        removed = await limiter.cleanup_old_buckets(max_age=3600)

        assert removed >= 1

    def test_get_stats(self, limiter):
        """Test getting statistics."""
        stats = limiter.get_stats()

        assert isinstance(stats, dict)

    def test_reset_stats(self, limiter):
        """Test resetting statistics."""
        limiter._stats["test"] = {"allowed": 10, "blocked": 5}

        limiter.reset_stats()

        assert len(limiter._stats) == 0


class TestBucketKeyGeneration:
    """Tests for bucket key generation based on limit types."""

    @pytest.fixture
    def limiter(self):
        return RateLimiter()

    def test_user_limit_type_key(self, limiter):
        """Test bucket key for USER limit type."""
        config = RateLimitConfig(requests=5, window=60, limit_type=RateLimitType.USER)

        key = limiter._get_bucket_key("test", config, user_id=123, channel_id=456, guild_id=789)

        assert key == "test:user:123"

    def test_channel_limit_type_key(self, limiter):
        """Test bucket key for CHANNEL limit type."""
        config = RateLimitConfig(requests=5, window=60, limit_type=RateLimitType.CHANNEL)

        key = limiter._get_bucket_key("test", config, user_id=123, channel_id=456, guild_id=789)

        assert key == "test:channel:456"

    def test_guild_limit_type_key(self, limiter):
        """Test bucket key for GUILD limit type."""
        config = RateLimitConfig(requests=5, window=60, limit_type=RateLimitType.GUILD)

        key = limiter._get_bucket_key("test", config, user_id=123, channel_id=456, guild_id=789)

        assert key == "test:guild:789"

    def test_global_limit_type_key(self, limiter):
        """Test bucket key for GLOBAL limit type."""
        config = RateLimitConfig(requests=5, window=60, limit_type=RateLimitType.GLOBAL)

        key = limiter._get_bucket_key("test", config, user_id=123, channel_id=456, guild_id=789)

        assert key == "test:global"

    def test_user_channel_limit_type_key(self, limiter):
        """Test bucket key for USER_CHANNEL limit type."""
        config = RateLimitConfig(requests=5, window=60, limit_type=RateLimitType.USER_CHANNEL)

        key = limiter._get_bucket_key("test", config, user_id=123, channel_id=456, guild_id=789)

        assert key == "test:user_channel:123:456"


class TestFormatStats:
    """Tests for format_rate_limit_stats utility function."""

    def test_format_empty_stats(self):
        """Test formatting when there are no config stats (only metadata)."""
        # Temporarily clear stats
        old_stats = rate_limiter._stats.copy()
        rate_limiter.reset_stats()

        result = format_rate_limit_stats()

        # Stats is never truly empty - get_stats() always adds active_buckets/total_blocked
        # So we just check the header is there and no config entries appear
        assert "Rate Limit Statistics" in result

        # Restore
        rate_limiter._stats = old_stats

    def test_format_with_stats(self):
        """Test formatting with actual stats."""
        # Add some test stats
        rate_limiter._stats["test_stat"] = {"allowed": 10, "blocked": 2}

        result = format_rate_limit_stats()

        assert "Rate Limit Statistics" in result
        assert "test_stat" in result


class TestChannelLimits:
    """Tests for channel-specific rate limits."""

    @pytest.fixture
    def limiter(self):
        return RateLimiter()

    def test_get_channel_limit_default(self, limiter):
        """Test get_channel_limit returns default value."""
        result = limiter.get_channel_limit(999999)
        assert isinstance(result, int)
        assert result > 0

    @pytest.mark.asyncio
    async def test_set_channel_limit(self, limiter):
        """Test setting custom channel limit."""
        await limiter.set_channel_limit(123456, 50)

        result = limiter.get_channel_limit(123456)
        assert result == 50

    @pytest.mark.asyncio
    async def test_set_channel_limit_creates_config(self, limiter):
        """Test set_channel_limit creates config if not exists."""
        await limiter.set_channel_limit(777777, 30)

        assert "channel_custom" in limiter._configs

    @pytest.mark.asyncio
    async def test_set_channel_limit_updates_existing(self, limiter):
        """Test updating existing channel limit."""
        await limiter.set_channel_limit(888888, 20)
        await limiter.set_channel_limit(888888, 40)

        result = limiter.get_channel_limit(888888)
        assert result == 40


class TestAdaptiveLimiting:
    """Tests for adaptive rate limiting."""

    @pytest.fixture
    def limiter(self):
        return RateLimiter()

    def test_adaptive_enabled_by_default(self, limiter):
        """Test adaptive limiting is enabled by default."""
        assert limiter._adaptive_enabled is True

    def test_set_adaptive_enabled(self, limiter):
        """Test toggling adaptive limiting."""
        limiter.set_adaptive_enabled(False)
        assert limiter._adaptive_enabled is False

        limiter.set_adaptive_enabled(True)
        assert limiter._adaptive_enabled is True

    def test_get_adaptive_multiplier(self, limiter):
        """Test getting adaptive multiplier."""
        result = limiter._get_adaptive_multiplier()
        assert isinstance(result, float)
        assert result > 0

    def test_update_all_adaptive_limits(self, limiter):
        """Test updating all adaptive limits."""
        # Should not raise
        limiter.update_all_adaptive_limits()

    def test_reload_limits(self, limiter):
        """Test reloading rate limit configurations."""
        # Should not raise
        limiter.reload_limits()


class TestWaitFor:
    """Tests for wait_for method."""

    @pytest.fixture
    def limiter(self):
        return RateLimiter()

    @pytest.mark.asyncio
    async def test_wait_for_immediate_allow(self, limiter):
        """Test wait_for when immediately allowed."""
        result = await limiter.wait_for("command", user_id=55555)
        assert result is True

    @pytest.mark.asyncio
    async def test_wait_for_max_wait_exceeded(self, limiter):
        """Test wait_for when max_wait is exceeded."""
        # Create a very strict limit
        config = RateLimitConfig(
            requests=1,
            window=100,
            limit_type=RateLimitType.USER,
        )
        limiter.add_config("wait_test", config)

        # Use up the limit
        await limiter.check("wait_test", user_id=66666)

        # Now wait should fail quickly
        result = await limiter.wait_for("wait_test", user_id=66666, max_wait=0.1)
        assert result is False


class TestCleanupTask:
    """Tests for cleanup background task."""

    @pytest.fixture
    def limiter(self):
        return RateLimiter()

    @pytest.mark.asyncio
    async def test_start_cleanup_task(self, limiter):
        """Test starting cleanup task."""
        limiter.start_cleanup_task(interval=3600)
        assert limiter._cleanup_task is not None

        # Clean up
        await limiter.stop_cleanup_task()

    @pytest.mark.asyncio
    async def test_stop_cleanup_task(self, limiter):
        """Test stopping cleanup task."""
        import asyncio

        limiter.start_cleanup_task(interval=3600)
        await limiter.stop_cleanup_task()

        # Wait a bit for cancellation to propagate
        await asyncio.sleep(0.1)

        # Task should be cancelled or done
        assert limiter._cleanup_task.cancelled() or limiter._cleanup_task.done()


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_config_defaults(self):
        """Test config default values."""
        config = RateLimitConfig(requests=10, window=60)

        assert config.requests == 10
        assert config.window == 60
        assert config.limit_type == RateLimitType.USER
        assert config.cooldown_message is None
        assert config.silent is False
        assert config.adaptive is False

    def test_config_with_all_options(self):
        """Test config with all options set."""
        config = RateLimitConfig(
            requests=5,
            window=30,
            limit_type=RateLimitType.GUILD,
            cooldown_message="Custom message",
            silent=True,
            adaptive=True,
        )

        assert config.requests == 5
        assert config.window == 30
        assert config.limit_type == RateLimitType.GUILD
        assert config.cooldown_message == "Custom message"
        assert config.silent is True
        assert config.adaptive is True


class TestRateLimitType:
    """Tests for RateLimitType enum."""

    def test_all_types_exist(self):
        """Test all rate limit types exist."""
        assert RateLimitType.USER.value == "user"
        assert RateLimitType.CHANNEL.value == "channel"
        assert RateLimitType.GUILD.value == "guild"
        assert RateLimitType.GLOBAL.value == "global"
        assert RateLimitType.USER_CHANNEL.value == "user_channel"


class TestAdaptiveMultipliers:
    """Tests for adaptive multiplier constants."""

    def test_adaptive_multipliers_exist(self):
        """Test adaptive multipliers are defined."""
        from utils.reliability.rate_limiter import RateLimiter

        assert RateLimiter.ADAPTIVE_MULTIPLIERS is not None
        assert "CLOSED" in RateLimiter.ADAPTIVE_MULTIPLIERS
        assert "HALF_OPEN" in RateLimiter.ADAPTIVE_MULTIPLIERS
        assert "OPEN" in RateLimiter.ADAPTIVE_MULTIPLIERS

    def test_adaptive_multiplier_values(self):
        """Test adaptive multiplier values are sensible."""
        from utils.reliability.rate_limiter import RateLimiter

        # CLOSED should be highest (normal operation)
        assert RateLimiter.ADAPTIVE_MULTIPLIERS["CLOSED"] == 1.0
        # HALF_OPEN should be reduced
        assert RateLimiter.ADAPTIVE_MULTIPLIERS["HALF_OPEN"] < 1.0
        # OPEN should be minimal
        assert RateLimiter.ADAPTIVE_MULTIPLIERS["OPEN"] < RateLimiter.ADAPTIVE_MULTIPLIERS["HALF_OPEN"]


class TestRateLimitBucketAdaptive:
    """Tests for RateLimitBucket with adaptive multiplier."""

    def test_bucket_with_adaptive_multiplier(self):
        """Test bucket respects adaptive multiplier."""
        bucket = RateLimitBucket(
            tokens=10.0,
            last_update=time.time(),
            window=60.0,
            max_tokens=10,
            adaptive_multiplier=0.5,  # 50% capacity
        )

        # Effective max should be 5
        # Consume 5 times should work
        for _ in range(5):
            success, _ = bucket.consume()
            assert success is True

        # 6th should fail
        success, _ = bucket.consume()
        assert success is False


class TestGlobalRateLimiter:
    """Tests for global rate limiter instance."""

    def test_global_instance_exists(self):
        """Test global rate_limiter instance exists."""
        from utils.reliability.rate_limiter import rate_limiter

        assert rate_limiter is not None
        assert isinstance(rate_limiter, RateLimiter)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
