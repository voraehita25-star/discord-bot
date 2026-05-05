"""
Token Usage Tracker Module.
Monitors and controls API costs per user/channel/guild.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..data.constants import DEFAULT_MODEL

logger = logging.getLogger(__name__)


def _aware_now() -> datetime:
    """Tz-aware UTC now. Naive datetime.now() compared against tz-aware
    timestamps loaded from the DB raises TypeError, which silently breaks
    rolling-window queries — use this everywhere instead."""
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime) -> datetime:
    """Promote a naive datetime to UTC. Used for legacy DB rows that may not
    carry an offset."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

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
        """Estimated cost in USD, model-aware.

        Pricing is approximate and may change. Check each provider's official
        page for current rates:
        - Claude: https://www.anthropic.com/pricing
        - Gemini: https://ai.google.dev/pricing
        """
        model_lower = (self.model or "").lower()
        # Explicit per-model rates checked by *prefix* so dated suffixes
        # (e.g. ``claude-opus-4-7-20251001``) match the canonical id
        # (``claude-opus-4-7``). Order matters: longer/more-specific
        # prefixes must come first.
        # (input_rate_per_M, output_rate_per_M) in USD per 1M tokens.
        _CLAUDE_PRICING: tuple[tuple[str, tuple[float, float]], ...] = (
            ("claude-opus-4-7", (15.0, 75.0)),
            ("claude-sonnet-4-6", (3.0, 15.0)),
            ("claude-haiku-4-5", (0.80, 4.0)),
        )
        for _prefix, (_in, _out) in _CLAUDE_PRICING:
            if model_lower.startswith(_prefix):
                input_rate = _in / 1_000_000
                output_rate = _out / 1_000_000
                return self.input_tokens * input_rate + self.output_tokens * output_rate
        # Family-level fallbacks for older / undated names.
        # Claude Opus 4.x family (~$15 input / $75 output per 1M tokens)
        if "opus" in model_lower:
            input_rate = 15.0 / 1_000_000
            output_rate = 75.0 / 1_000_000
        # Claude Sonnet family (~$3 input / $15 output per 1M)
        elif "sonnet" in model_lower:
            input_rate = 3.0 / 1_000_000
            output_rate = 15.0 / 1_000_000
        # Claude Haiku family (~$0.80 input / $4 output per 1M)
        elif "haiku" in model_lower:
            input_rate = 0.80 / 1_000_000
            output_rate = 4.0 / 1_000_000
        # Unknown Claude model — log a warning and conservatively use Sonnet
        # rates so we don't silently undercharge an Opus-class request.
        elif "claude" in model_lower:
            logger.warning(
                "Unrecognized Claude model %r — defaulting to Sonnet pricing for cost estimate",
                self.model,
            )
            input_rate = 3.0 / 1_000_000
            output_rate = 15.0 / 1_000_000
        # Gemini explicitly — Flash tier rates
        elif "gemini" in model_lower or "google" in model_lower:
            input_rate = 0.10 / 1_000_000
            output_rate = 0.40 / 1_000_000
        # Unknown provider — log loudly. Prior behaviour silently billed
        # OpenAI/o3/etc. at Gemini Flash rates (~100x under-report). Use a
        # mid-tier rate (Sonnet-like) so the estimate at least flags as
        # non-trivial cost while the operator investigates.
        else:
            logger.warning(
                "Unknown AI model %r — token cost estimate will use generic mid-tier rate. "
                "Add explicit pricing in cogs/ai_core/cache/token_tracker.py.",
                self.model,
            )
            input_rate = 3.0 / 1_000_000
            output_rate = 15.0 / 1_000_000
        return self.input_tokens * input_rate + self.output_tokens * output_rate


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

    # Maximum records per cache key to prevent unbounded growth between cleanups
    MAX_RECORDS_PER_KEY = 5000

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

    async def init_from_db(self, hours: int = 24, max_rows: int = 10_000) -> int:
        """Pre-populate the in-memory cache from the ``token_usage`` table.

        Quotas are enforced against ``_usage_cache``, which is empty after a
        process restart — so without this call, ``check_limits`` would let a
        user blow past their hourly limit until enough new requests refilled
        the cache. We replay the last ``hours`` worth of recorded usage so
        post-restart quotas line up with what was already spent.

        Returns the number of records loaded. Called from bot startup; safe
        to call multiple times (each call re-reads from DB, replacing any
        records currently in the same time window).
        """
        if not DB_AVAILABLE or db is None:
            return 0

        cutoff = _aware_now() - timedelta(hours=hours)
        try:
            async with db.get_connection() as conn:
                # ORDER BY ASC so the trim-from-front logic at the end keeps
                # the NEWEST records (the tail), matching the eviction
                # semantics _record_usage relies on. Previously the DESC
                # order combined with `[-MAX_RECORDS_PER_KEY:]` kept the
                # oldest records, which is the opposite of intent.
                cursor = await conn.execute(
                    """SELECT user_id, channel_id, guild_id, input_tokens,
                              output_tokens, model, cached, created_at
                       FROM token_usage
                       WHERE created_at >= ?
                       ORDER BY created_at ASC
                       LIMIT ?""",
                    (cutoff.isoformat(), max_rows),
                )
                rows = await cursor.fetchall()
        except Exception as e:
            self.logger.warning("Failed to load token_usage history: %s", e)
            return 0

        if not rows:
            return 0

        loaded = 0
        async with self._lock:
            # Idempotency: clear existing entries within the replay window so
            # repeated calls don't double-count the same DB rows. We rebuild
            # only the windowed slice; older records (outside [cutoff, now])
            # in the cache stay untouched in case _record_usage produced any
            # in-memory entries in the meantime.
            for cache_key in list(self._usage_cache.keys()):
                self._usage_cache[cache_key] = [
                    u for u in self._usage_cache[cache_key] if u.timestamp < cutoff
                ]

            for row in rows:
                try:
                    ts_raw = row[7]
                    ts = (
                        _ensure_aware(datetime.fromisoformat(ts_raw))
                        if isinstance(ts_raw, str)
                        else _aware_now()
                    )
                    usage = TokenUsage(
                        user_id=int(row[0]),
                        channel_id=int(row[1]),
                        guild_id=int(row[2]) if row[2] is not None else None,
                        input_tokens=int(row[3] or 0),
                        output_tokens=int(row[4] or 0),
                        model=row[5] or DEFAULT_MODEL,
                        cached=bool(row[6]),
                        timestamp=ts,
                    )
                except (TypeError, ValueError) as e:
                    self.logger.debug("Skipping malformed token_usage row: %s", e)
                    continue

                self._usage_cache[f"user:{usage.user_id}"].append(usage)
                self._usage_cache[f"channel:{usage.channel_id}"].append(usage)
                if usage.guild_id is not None:
                    self._usage_cache[f"guild:{usage.guild_id}"].append(usage)
                loaded += 1

            # Trim each key to the cap in case the DB had more than
            # MAX_RECORDS_PER_KEY rows for one user.
            for key in self._usage_cache:
                if len(self._usage_cache[key]) > self.MAX_RECORDS_PER_KEY:
                    self._usage_cache[key] = self._usage_cache[key][-self.MAX_RECORDS_PER_KEY:]

        self.logger.info(
            "📊 Token tracker pre-populated: %d records from last %dh", loaded, hours
        )
        return loaded

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
                # Continue running — next iteration will retry after sleep

    async def _cleanup_old_records(self) -> None:
        """Remove records older than 7 days from memory cache."""
        cutoff = _aware_now() - timedelta(days=7)
        async with self._lock:
            for key in list(self._usage_cache.keys()):
                self._usage_cache[key] = [
                    u for u in self._usage_cache[key]
                    if _ensure_aware(u.timestamp) > cutoff
                ]
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
            if len(self._usage_cache[user_key]) > self.MAX_RECORDS_PER_KEY:
                self._usage_cache[user_key] = self._usage_cache[user_key][-self.MAX_RECORDS_PER_KEY:]

            # Store by channel
            channel_key = f"channel:{usage.channel_id}"
            self._usage_cache[channel_key].append(usage)
            if len(self._usage_cache[channel_key]) > self.MAX_RECORDS_PER_KEY:
                self._usage_cache[channel_key] = self._usage_cache[channel_key][-self.MAX_RECORDS_PER_KEY:]

            # Store by guild if available. Use `is not None` because guild
            # IDs are always positive Discord snowflakes, but `if usage.guild_id`
            # would also drop a hypothetical 0 — better to be explicit.
            if usage.guild_id is not None:
                guild_key = f"guild:{usage.guild_id}"
                self._usage_cache[guild_key].append(usage)
                if len(self._usage_cache[guild_key]) > self.MAX_RECORDS_PER_KEY:
                    self._usage_cache[guild_key] = self._usage_cache[guild_key][-self.MAX_RECORDS_PER_KEY:]

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
            async with db.get_write_connection() as conn:
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
        cutoff = _aware_now() - period
        # Return a copy to avoid modification during iteration
        records = self._usage_cache.get(key, [])
        return [u for u in records if _ensure_aware(u.timestamp) > cutoff]

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

        # Check for warning threshold. Treat daily_user_tokens<=0 as
        # "unlimited" rather than crashing with ZeroDivisionError.
        warning = None
        if self.limits.daily_user_tokens > 0:
            usage_ratio = daily_stats.total_tokens / self.limits.daily_user_tokens
            if usage_ratio >= self.limits.warning_threshold:
                remaining = self.limits.daily_user_tokens - daily_stats.total_tokens
                warning = f"💡 เหลือโควต้าวันนี้ประมาณ {remaining:,} tokens"

        return True, warning

    async def get_global_stats(self) -> dict[str, Any]:
        """Get global usage statistics."""
        # Acquire lock to safely iterate shared mutable lists
        async with self._lock:
            cache_snapshot = {k: list(v) for k, v in self._usage_cache.items()}
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
