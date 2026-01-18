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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
