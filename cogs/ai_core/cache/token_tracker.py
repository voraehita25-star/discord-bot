"""
Token Usage Tracker Module.
Monitors and controls API costs per user/channel/guild.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..data.constants import DEFAULT_MODEL

# Try to import database
try:
    from utils.database import db

    DB_AVAILABLE = True
except ImportError:
    db = None  # type: ignore
    DB_AVAILABLE = False


@dataclass
class TokenUsage:
    """Record of a single API call's token usage."""

    input_tokens: int
    output_tokens: int
    timestamp: datetime
    user_id: int
    channel_id: int
    guild_id: int | None = None
    model: str = DEFAULT_MODEL
    cached: bool = False

    @property
    def total_tokens(self) -> int:
        """Total tokens used in this request."""
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost(self) -> float:
        """Estimated cost in USD (based on Gemini pricing).

        Note: Pricing is approximate and may change. Check Google's official
        pricing page for current rates: https://ai.google.dev/pricing

        Current estimates (as of 2024):
        - Input: $0.10 per 1M tokens
        - Output: $0.40 per 1M tokens
        """
        input_cost = (self.input_tokens / 1_000_000) * 0.10
        output_cost = (self.output_tokens / 1_000_000) * 0.40
        return input_cost + output_cost


@dataclass
class UsageLimits:
    """Configurable usage limits."""

    daily_user_tokens: int = 100_000  # Per user per day
    daily_channel_tokens: int = 500_000  # Per channel per day
    daily_guild_tokens: int = 2_000_000  # Per guild per day
    hourly_user_tokens: int = 20_000  # Per user per hour
    warning_threshold: float = 0.8  # Warn at 80% usage


@dataclass
class UsageStats:
    """Aggregated usage statistics."""

    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0
    cached_count: int = 0
    estimated_cost: float = 0.0
    period_start: datetime | None = None
    period_end: datetime | None = None


class TokenTracker:
    """
    Tracks and manages API token usage.

    Features:
    - Per-user, per-channel, per-guild tracking
    - Configurable limits with warnings
    - Historical data persistence
    - Cost estimation
    """

    def __init__(self, limits: UsageLimits | None = None):
        self.limits = limits or UsageLimits()
        self._usage_cache: dict[str, list[TokenUsage]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None
        self.logger = logging.getLogger("TokenTracker")

    def start_cleanup_task(self) -> None:
        """Start background cleanup of old usage data."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())
            self.logger.info("📊 Token tracker cleanup task started")

    def stop_cleanup_task(self) -> None:
        """Stop the cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            self._cleanup_task = None

    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of old usage records."""
        while True:
            try:
                await asyncio.sleep(3600)  # Every hour
                await self._cleanup_old_records()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Token tracker cleanup error: %s", e)

    async def _cleanup_old_records(self) -> None:
        """Remove records older than 7 days from memory cache."""
        cutoff = datetime.now() - timedelta(days=7)
        async with self._lock:
            for key in list(self._usage_cache.keys()):
                self._usage_cache[key] = [u for u in self._usage_cache[key] if u.timestamp > cutoff]
                if not self._usage_cache[key]:
                    del self._usage_cache[key]
        self.logger.debug("🧹 Cleaned up old token usage records")

    async def record_usage(self, usage: TokenUsage) -> None:
        """
        Record a token usage event.

        Args:
            usage: TokenUsage record to store
        """
        async with self._lock:
            # Store by user
            user_key = f"user:{usage.user_id}"
            self._usage_cache[user_key].append(usage)

            # Store by channel
            channel_key = f"channel:{usage.channel_id}"
            self._usage_cache[channel_key].append(usage)

            # Store by guild if available
            if usage.guild_id:
                guild_key = f"guild:{usage.guild_id}"
                self._usage_cache[guild_key].append(usage)

        # Persist to database if available
        if DB_AVAILABLE:
            await self._persist_usage(usage)

        self.logger.debug(
            "📊 Recorded usage: user=%s, tokens=%d (in=%d, out=%d)",
            usage.user_id,
            usage.total_tokens,
            usage.input_tokens,
            usage.output_tokens,
        )

    async def _persist_usage(self, usage: TokenUsage) -> None:
        """Persist usage to database."""
        if not DB_AVAILABLE or db is None:
            return

        try:
            async with db.get_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO token_usage
                    (user_id, channel_id, guild_id, input_tokens, output_tokens,
                     model, cached, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        usage.user_id,
                        usage.channel_id,
                        usage.guild_id,
                        usage.input_tokens,
                        usage.output_tokens,
                        usage.model,
                        usage.cached,
                        usage.timestamp.isoformat(),
                    ),
                )
        except Exception as e:
            self.logger.warning("Failed to persist token usage: %s", e)

    def _get_usage_in_period(self, key: str, period: timedelta) -> list[TokenUsage]:
        """Get usage records within a time period (returns snapshot, caller should use with lock if needed)."""
        cutoff = datetime.now() - period
        # Return a copy to avoid modification during iteration
        records = self._usage_cache.get(key, [])
        return [u for u in records if u.timestamp > cutoff]

    async def get_usage_in_period_safe(self, key: str, period: timedelta) -> list[TokenUsage]:
        """Thread-safe version of _get_usage_in_period."""
        async with self._lock:
            return self._get_usage_in_period(key, period)

    def _aggregate_usage(self, records: list[TokenUsage]) -> UsageStats:
        """Aggregate multiple usage records into stats."""
        if not records:
            return UsageStats()

        stats = UsageStats(
            period_start=min(r.timestamp for r in records),
            period_end=max(r.timestamp for r in records),
        )

        for record in records:
            stats.total_tokens += record.total_tokens
            stats.input_tokens += record.input_tokens
            stats.output_tokens += record.output_tokens
            stats.request_count += 1
            stats.estimated_cost += record.estimated_cost
            if record.cached:
                stats.cached_count += 1

        return stats

    async def get_user_usage(self, user_id: int, period: str = "day") -> UsageStats:
        """
        Get token usage for a specific user.

        Args:
            user_id: Discord user ID
            period: "hour", "day", or "week"

        Returns:
            UsageStats for the user in the specified period
        """
        period_delta = {
            "hour": timedelta(hours=1),
            "day": timedelta(days=1),
            "week": timedelta(weeks=1),
        }.get(period, timedelta(days=1))

        key = f"user:{user_id}"
        async with self._lock:
            records = self._get_usage_in_period(key, period_delta)
        return self._aggregate_usage(records)

    async def get_channel_usage(self, channel_id: int, period: str = "day") -> UsageStats:
        """Get token usage for a specific channel."""
        period_delta = {
            "hour": timedelta(hours=1),
            "day": timedelta(days=1),
            "week": timedelta(weeks=1),
        }.get(period, timedelta(days=1))

        key = f"channel:{channel_id}"
        async with self._lock:
            records = self._get_usage_in_period(key, period_delta)
        return self._aggregate_usage(records)

    async def get_guild_usage(self, guild_id: int, period: str = "day") -> UsageStats:
        """Get token usage for a specific guild."""
        period_delta = {
            "hour": timedelta(hours=1),
            "day": timedelta(days=1),
            "week": timedelta(weeks=1),
        }.get(period, timedelta(days=1))

        key = f"guild:{guild_id}"
        async with self._lock:
            records = self._get_usage_in_period(key, period_delta)
        return self._aggregate_usage(records)

    async def check_limits(
        self, user_id: int, channel_id: int | None = None, guild_id: int | None = None
    ) -> tuple[bool, str | None]:
        """
        Check if user/channel/guild is within limits.

        Returns:
            Tuple of (is_allowed, warning_message)
            - is_allowed: True if request should proceed
            - warning_message: Optional warning if approaching limit
        """
        # Check hourly user limit
        hourly_stats = await self.get_user_usage(user_id, "hour")
        if hourly_stats.total_tokens >= self.limits.hourly_user_tokens:
            return False, "⚠️ คุณใช้โควต้ารายชั่วโมงหมดแล้ว กรุณารอสักครู่"

        # Check daily user limit
        daily_stats = await self.get_user_usage(user_id, "day")
        if daily_stats.total_tokens >= self.limits.daily_user_tokens:
            return False, "⚠️ คุณใช้โควต้ารายวันหมดแล้ว กรุณารอจนถึงพรุ่งนี้"

        # Check daily channel limit
        if channel_id:
            channel_stats = await self.get_channel_usage(channel_id, "day")
            if channel_stats.total_tokens >= self.limits.daily_channel_tokens:
                return False, "⚠️ ห้องนี้ใช้โควต้าหมดแล้ววันนี้"

        # Check daily guild limit
        if guild_id:
            guild_stats = await self.get_guild_usage(guild_id, "day")
            if guild_stats.total_tokens >= self.limits.daily_guild_tokens:
                return False, "⚠️ เซิร์ฟเวอร์นี้ใช้โควต้าหมดแล้ววันนี้"

        # Check for warning threshold
        warning = None
        usage_ratio = daily_stats.total_tokens / self.limits.daily_user_tokens
        if usage_ratio >= self.limits.warning_threshold:
            remaining = self.limits.daily_user_tokens - daily_stats.total_tokens
            warning = f"💡 เหลือโควต้าวันนี้ประมาณ {remaining:,} tokens"

        return True, warning

    def get_global_stats(self) -> dict[str, Any]:
        """Get global usage statistics."""
        # Take a snapshot of keys to avoid RuntimeError during iteration
        cache_snapshot = dict(self._usage_cache)
        # Calculate from user records only to avoid double/triple counting
        user_records = {k: v for k, v in cache_snapshot.items() if k.startswith("user:")}
        total_tokens = sum(
            sum(r.total_tokens for r in records) for records in user_records.values()
        )
        total_requests = sum(len(records) for records in user_records.values())

        return {
            "total_records": total_requests,
            "total_tokens": total_tokens,
            "unique_users": len(user_records),
            "unique_channels": len([k for k in cache_snapshot if k.startswith("channel:")]),
            "unique_guilds": len([k for k in cache_snapshot if k.startswith("guild:")]),
        }


# Global instance
token_tracker = TokenTracker()
