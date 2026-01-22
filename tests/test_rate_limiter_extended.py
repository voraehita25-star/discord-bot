"""
Tests for utils.reliability.rate_limiter module (extended).
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import time


class TestRateLimitType:
    """Tests for RateLimitType enum."""

    def test_user_type(self):
        """Test USER type."""
        from utils.reliability.rate_limiter import RateLimitType
        
        assert RateLimitType.USER.value == "user"

    def test_channel_type(self):
        """Test CHANNEL type."""
        from utils.reliability.rate_limiter import RateLimitType
        
        assert RateLimitType.CHANNEL.value == "channel"

    def test_guild_type(self):
        """Test GUILD type."""
        from utils.reliability.rate_limiter import RateLimitType
        
        assert RateLimitType.GUILD.value == "guild"

    def test_global_type(self):
        """Test GLOBAL type."""
        from utils.reliability.rate_limiter import RateLimitType
        
        assert RateLimitType.GLOBAL.value == "global"

    def test_user_channel_type(self):
        """Test USER_CHANNEL type."""
        from utils.reliability.rate_limiter import RateLimitType
        
        assert RateLimitType.USER_CHANNEL.value == "user_channel"


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_create_basic_config(self):
        """Test creating basic config."""
        from utils.reliability.rate_limiter import RateLimitConfig, RateLimitType
        
        config = RateLimitConfig(requests=5, window=60.0)
        
        assert config.requests == 5
        assert config.window == 60.0
        assert config.limit_type == RateLimitType.USER

    def test_config_with_all_params(self):
        """Test config with all parameters."""
        from utils.reliability.rate_limiter import RateLimitConfig, RateLimitType
        
        config = RateLimitConfig(
            requests=10,
            window=30.0,
            limit_type=RateLimitType.GUILD,
            cooldown_message="Slow down!",
            silent=True,
            adaptive=True
        )
        
        assert config.requests == 10
        assert config.window == 30.0
        assert config.limit_type == RateLimitType.GUILD
        assert config.cooldown_message == "Slow down!"
        assert config.silent is True
        assert config.adaptive is True


class TestRateLimitBucket:
    """Tests for RateLimitBucket dataclass."""

    def test_create_bucket(self):
        """Test creating bucket."""
        from utils.reliability.rate_limiter import RateLimitBucket
        
        bucket = RateLimitBucket(
            tokens=5.0,
            last_update=time.time(),
            window=60.0,
            max_tokens=5
        )
        
        assert bucket.tokens == 5.0
        assert bucket.max_tokens == 5

    def test_consume_success(self):
        """Test consuming when tokens available."""
        from utils.reliability.rate_limiter import RateLimitBucket
        
        bucket = RateLimitBucket(
            tokens=5.0,
            last_update=time.time(),
            window=60.0,
            max_tokens=5
        )
        
        success, retry_after = bucket.consume()
        
        assert success is True
        assert retry_after == 0.0
        assert bucket.tokens < 5.0

    def test_consume_failure(self):
        """Test consuming when no tokens."""
        from utils.reliability.rate_limiter import RateLimitBucket
        
        bucket = RateLimitBucket(
            tokens=0.0,
            last_update=time.time(),
            window=60.0,
            max_tokens=5
        )
        
        success, retry_after = bucket.consume()
        
        assert success is False
        assert retry_after > 0

    def test_consume_replenishes_tokens(self):
        """Test tokens replenish over time."""
        from utils.reliability.rate_limiter import RateLimitBucket
        
        bucket = RateLimitBucket(
            tokens=0.0,
            last_update=time.time() - 60,  # 60 seconds ago
            window=60.0,
            max_tokens=5
        )
        
        success, _ = bucket.consume()
        
        # Should have replenished
        assert success is True


class TestRateLimiterInit:
    """Tests for RateLimiter initialization."""

    def test_create_rate_limiter(self):
        """Test creating RateLimiter."""
        from utils.reliability.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        assert limiter is not None

    def test_limiter_has_buckets(self):
        """Test limiter initializes buckets."""
        from utils.reliability.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        assert hasattr(limiter, '_buckets')

    def test_limiter_has_stats(self):
        """Test limiter initializes stats."""
        from utils.reliability.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        assert hasattr(limiter, '_stats')


class TestRateLimiterCheckRateLimit:
    """Tests for RateLimiter.check method."""

    @pytest.mark.asyncio
    async def test_check_allows_first_request(self):
        """Test first request is allowed."""
        from utils.reliability.rate_limiter import RateLimiter, RateLimitConfig
        
        limiter = RateLimiter()
        
        # Add a config first
        config = RateLimitConfig(requests=5, window=60.0)
        limiter.add_config("test", config)
        
        allowed, retry_after, msg = await limiter.check("test", user_id=123)
        
        assert allowed is True
        assert retry_after == 0.0

    @pytest.mark.asyncio
    async def test_check_blocks_after_limit(self):
        """Test requests blocked after limit reached."""
        from utils.reliability.rate_limiter import RateLimiter, RateLimitConfig
        
        limiter = RateLimiter()
        config = RateLimitConfig(requests=2, window=60.0)
        limiter.add_config("test2", config)
        
        # Use up all tokens
        await limiter.check("test2", user_id=123)
        await limiter.check("test2", user_id=123)
        
        # Third request should be blocked
        allowed, retry_after, msg = await limiter.check("test2", user_id=123)
        
        assert allowed is False
        assert retry_after > 0


class TestRateLimiterStats:
    """Tests for rate limiter statistics."""

    def test_get_stats(self):
        """Test getting stats."""
        from utils.reliability.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        stats = limiter.get_stats()
        
        assert isinstance(stats, dict)


class TestRateLimitConstants:
    """Tests for rate limit constants."""

    def test_circuit_breaker_available_flag(self):
        """Test CIRCUIT_BREAKER_AVAILABLE flag."""
        from utils.reliability.rate_limiter import CIRCUIT_BREAKER_AVAILABLE
        
        assert isinstance(CIRCUIT_BREAKER_AVAILABLE, bool)


class TestRateLimiterCleanup:
    """Tests for cleanup functionality."""

    @pytest.mark.asyncio
    async def test_cleanup_old_buckets(self):
        """Test cleanup_old_buckets method."""
        from utils.reliability.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        
        if hasattr(limiter, 'cleanup_old_buckets'):
            await limiter.cleanup_old_buckets()
            # Should complete without error

    def test_limiter_has_cleanup_interval(self):
        """Test limiter has cleanup interval setting."""
        from utils.reliability.rate_limiter import RateLimiter
        
        limiter = RateLimiter()
        
        if hasattr(limiter, '_cleanup_interval'):
            assert limiter._cleanup_interval > 0
