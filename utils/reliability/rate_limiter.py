"""
Rate Limiter Module for Discord Bot
Provides rate limiting for API calls and commands.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar

import discord
from discord.ext import commands

# Try to import circuit breaker for adaptive limiting
try:
    from .circuit_breaker import CircuitState, gemini_circuit

    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    CIRCUIT_BREAKER_AVAILABLE = False
    CircuitState = None  # type: ignore[assignment, misc]
    gemini_circuit = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


class RateLimitType(Enum):
    """Types of rate limiting."""

    USER = "user"  # Per user
    CHANNEL = "channel"  # Per channel
    GUILD = "guild"  # Per guild/server
    GLOBAL = "global"  # Global (all users)
    USER_CHANNEL = "user_channel"  # Per user per channel


# Using slots=True for memory efficiency
@dataclass(slots=True)
class RateLimitConfig:
    """Configuration for a rate limit."""

    requests: int  # Number of requests allowed
    window: float  # Time window in seconds
    limit_type: RateLimitType = RateLimitType.USER
    cooldown_message: str | None = None
    silent: bool = False  # If True, don't send cooldown message
    adaptive: bool = False  # If True, adjust based on API health

    def __post_init__(self) -> None:
        # Fail loudly at config time rather than under the bucket lock at
        # request time: a window <= 0 would raise ZeroDivisionError inside
        # RateLimitBucket.consume, and requests < 1 is a nonsensical limit
        # (it silently clamps to 1 downstream).
        if self.window <= 0:
            raise ValueError(f"RateLimitConfig.window must be > 0, got {self.window}")
        if self.requests < 1:
            raise ValueError(f"RateLimitConfig.requests must be >= 1, got {self.requests}")


@dataclass(slots=True)
class RateLimitBucket:
    """Tracks rate limit state for a single bucket."""

    tokens: float
    last_update: float
    window: float
    max_tokens: int
    adaptive_multiplier: float = 1.0  # For adaptive limiting

    def consume(self) -> tuple[bool, float]:
        """
        Try to consume a token. Returns (success, retry_after).
        Uses token bucket algorithm for smooth rate limiting.
        """
        now = time.time()

        # Replenish tokens based on time passed.
        # ``max(0, ...)`` defends against NTP backsteps or manual system
        # clock changes producing a negative ``time_passed`` that would
        # silently drain the bucket below zero. (Switching to
        # ``time.monotonic`` would also fix this, but the existing test
        # suite stores ``time.time()`` values directly in ``last_update``
        # so the wall clock stays here for compat.)
        # Additional cap at one full window so a FORWARD clock jump
        # (NTP, suspend/resume, manual change) can't gift unlimited
        # tokens — the worst the cap permits is "replenish the bucket
        # all the way" rather than "burst N*ratio tokens at once".
        time_passed = min(self.window, max(0.0, now - self.last_update))
        effective_max = max(1, int(self.max_tokens * self.adaptive_multiplier))
        # Clamp tokens to effective_max (handles adaptive_multiplier drops).
        # The outer ``min`` on line above already caps the result — a
        # second ``min`` would be a no-op.
        self.tokens = min(effective_max, self.tokens + (time_passed * effective_max / self.window))
        self.last_update = now

        if self.tokens >= 1:
            self.tokens -= 1
            return True, 0.0
        else:
            # Calculate retry after
            retry_after = (1 - self.tokens) * self.window / max(1, effective_max)
            return False, retry_after


class RateLimiter:
    """
    Rate limiter with multiple strategies and configurations.

    Features:
    - Token bucket algorithm for smooth limiting
    - Per-user, per-channel, per-guild, and global limits
    - Configurable cooldown messages
    - Auto-cleanup of old buckets
    - Statistics tracking
    - Per-bucket locks for better concurrency (optimized)
    - Adaptive limiting based on circuit breaker state
    """

    # Adaptive rate multipliers based on circuit state
    ADAPTIVE_MULTIPLIERS: ClassVar[dict[str, float]] = {
        "CLOSED": 1.0,  # Normal operation
        "HALF_OPEN": 0.5,  # Recovering - reduce by 50%
        "OPEN": 0.1,  # Circuit open - minimal traffic
    }

    # Max buckets to prevent unbounded memory growth
    MAX_BUCKETS = 10000

    # Default per-channel Gemini requests-per-minute. Single source of truth
    # for both the "gemini_api" config in _setup_defaults and the default
    # branch of get_channel_limit, so the documented default can't drift from
    # the configured value.
    DEFAULT_GEMINI_RPM = 60

    def __init__(self) -> None:
        self._buckets: dict[str, RateLimitBucket] = {}
        self._configs: dict[str, RateLimitConfig] = {}
        # Owner-set per-channel limits (!channel_ratelimit). Kept OUTSIDE the
        # evictable bucket dict so an idle hour doesn't silently erase the
        # admin's setting.
        self._channel_limits: dict[int, int] = {}
        self._stats: dict[str, dict[str, int]] = defaultdict(lambda: {"allowed": 0, "blocked": 0})
        # Per-bucket locks - using regular dict to prevent auto-creation after cleanup
        self._locks: dict[str, asyncio.Lock] = {}
        self._cleanup_task: asyncio.Task | None = None
        self._adaptive_enabled = True

        # Default configurations
        self._setup_defaults()

        logger.info("⏱️ Rate Limiter initialized (adaptive enabled)")

    def _setup_defaults(self) -> None:
        """Setup default rate limit configurations."""
        # Gemini API limits (conservative)
        self.add_config(
            "gemini_api",
            RateLimitConfig(
                requests=self.DEFAULT_GEMINI_RPM,  # 60 requests (raised for a small trusted group)
                window=60,  # per minute
                limit_type=RateLimitType.USER,
                cooldown_message="⏳ กรุณารอ {retry:.1f} วินาที ก่อนส่งข้อความถัดไป",
            ),
        )

        # Stricter global limit for Gemini
        self.add_config(
            "gemini_global",
            RateLimitConfig(
                requests=300,  # 300 requests (raised; still guards against Anthropic 429s)
                window=60,  # per minute globally
                limit_type=RateLimitType.GLOBAL,
                cooldown_message="⏳ ระบบ AI กำลังยุ่ง กรุณารอ {retry:.1f} วินาที",
            ),
        )

        # Music commands
        self.add_config(
            "music_command",
            RateLimitConfig(
                requests=10,  # 10 commands
                window=30,  # per 30 seconds
                limit_type=RateLimitType.USER,
                cooldown_message="🎵 รอสักครู่ก่อนใช้คำสั่งเพลงอีกครั้ง ({retry:.1f}s)",
            ),
        )

        # General commands
        self.add_config(
            "command",
            RateLimitConfig(
                requests=20,  # 20 commands (raised for a small trusted group)
                window=10,  # per 10 seconds
                limit_type=RateLimitType.USER,
                cooldown_message="⏳ กรุณารอ {retry:.1f} วินาที",
            ),
        )

        # Spam prevention (anti-flood; loosened for a trusted group)
        self.add_config(
            "spam",
            RateLimitConfig(
                requests=10,  # 10 messages
                window=5,  # per 5 seconds
                limit_type=RateLimitType.USER_CHANNEL,
                cooldown_message="🚫 ส่งข้อความช้าลงหน่อยนะ",
                silent=False,
            ),
        )

        # AI Server Management commands (per-guild limit)
        self.add_config(
            "server_management",
            RateLimitConfig(
                requests=30,  # 30 operations (raised)
                window=60,  # per minute per guild
                limit_type=RateLimitType.GUILD,
                cooldown_message="🔒 ถึงขีดจำกัดการจัดการ server แล้ว รอ {retry:.1f} วินาที",
            ),
        )

        # AI Tool calls (per-user limit for channel/role creation)
        self.add_config(
            "ai_tool_call",
            RateLimitConfig(
                requests=30,  # 30 tool calls (raised)
                window=60,  # per minute
                limit_type=RateLimitType.USER,
                cooldown_message="⏳ AI กำลังทำงานมากเกินไป รอ {retry:.1f} วินาที",
            ),
        )

        # AI Chat (per-guild limit to prevent one guild from monopolizing)
        self.add_config(
            "ai_guild",
            RateLimitConfig(
                requests=240,  # 240 AI requests (raised; ~4-5 active users)
                window=60,  # per minute per guild
                limit_type=RateLimitType.GUILD,
                cooldown_message="⏳ เซิร์ฟเวอร์นี้ใช้ AI ถึงขีดจำกัดแล้ว รอ {retry:.1f} วินาที",
                adaptive=True,
            ),
        )

        # AI Chat (per-user stricter limit)
        self.add_config(
            "ai_user",
            RateLimitConfig(
                requests=60,  # 60 AI requests (raised for a small trusted group)
                window=60,  # per minute per user
                limit_type=RateLimitType.USER,
                cooldown_message="⏳ คุณส่งข้อความ AI เร็วเกินไป รอ {retry:.1f} วินาที",
                adaptive=True,
            ),
        )

    def add_config(self, name: str, config: RateLimitConfig) -> None:
        """Add or update a rate limit configuration."""
        self._configs[name] = config

    def _get_bucket_key(
        self,
        config_name: str,
        config: RateLimitConfig,
        user_id: int | None = None,
        channel_id: int | None = None,
        guild_id: int | None = None,
    ) -> str:
        """Generate a unique bucket key based on limit type."""
        if config.limit_type == RateLimitType.USER:
            return f"{config_name}:user:{user_id}"
        elif config.limit_type == RateLimitType.CHANNEL:
            return f"{config_name}:channel:{channel_id}"
        elif config.limit_type == RateLimitType.GUILD:
            return f"{config_name}:guild:{guild_id}"
        elif config.limit_type == RateLimitType.GLOBAL:
            return f"{config_name}:global"
        elif config.limit_type == RateLimitType.USER_CHANNEL:
            return f"{config_name}:user_channel:{user_id}:{channel_id}"
        else:
            return f"{config_name}:unknown"

    @staticmethod
    def _config_name_from_key(key: str) -> str:
        """Recover the config name from a bucket key.

        Bucket keys are ``{config_name}:{type_tail}`` (see _get_bucket_key),
        but ``config_name`` itself may contain colons (owner-set per-channel
        configs are named ``channel_custom:{CID}``). A naive ``split(":")[0]``
        therefore mis-parses those, so reload_limits/update_all_adaptive_limits
        would fail to look up the config and silently skip the bucket. Strip
        the KNOWN type tail instead.

        Tails — the trailing portion (from the matched separator onward)
        contains a fixed number of colons; checking it avoids matching a
        ``:channel:`` that happens to sit inside the config name itself:
          - ``:user_channel:{uid}:{cid}``  → 3 colons
          - ``:user:{uid}`` / ``:channel:{cid}`` / ``:guild:{gid}`` → 2 colons
          - ``:global``                                            → 0 (no tail id)
        Longest token first so ``user_channel`` wins over ``channel``.
        """
        for token, tail_colons in (("user_channel", 3), ("user", 2), ("channel", 2), ("guild", 2)):
            sep = f":{token}:"
            idx = key.rfind(sep)
            if idx != -1 and key.count(":", idx) == tail_colons:
                return key[:idx]
        if key.endswith(":global"):
            return key[: -len(":global")]
        # Unknown shape — fall back to the legacy split (still correct for
        # built-in colon-free config names).
        return key.split(":", 1)[0]

    def _get_or_create_bucket(self, key: str, config: RateLimitConfig) -> RateLimitBucket | None:
        """Get existing bucket or create a new one.

        Returns ``None`` when the bucket pool is exhausted *and* every
        existing bucket is locked by a concurrent caller — the previous
        behaviour routed every overflow to a single shared ``__overflow__``
        bucket, which let one noisy key burn the tokens of every other key
        and turned the safety valve into a DoS amplifier. The caller must
        treat ``None`` as a deny.

        Note: This is called within an async lock context, so race conditions
        are already handled. Using setdefault for additional safety.
        Enforces MAX_BUCKETS limit to prevent unbounded memory growth.
        """
        # Check if bucket limit reached and evict oldest if necessary
        if key not in self._buckets and len(self._buckets) >= self.MAX_BUCKETS:
            # Find oldest bucket that is NOT currently locked (safe eviction).
            # Take a snapshot of the keys so concurrent mutation of
            # ``_buckets`` (other coroutines creating/deleting buckets after
            # we yield via the per-key lock check) can't raise
            # ``RuntimeError: dictionary changed size during iteration``.
            snapshot_keys = list(self._buckets.keys())
            sorted_keys = sorted(
                snapshot_keys,
                key=lambda k: self._buckets[k].last_update if k in self._buckets else float("inf"),
            )
            evicted = False
            for candidate_key in sorted_keys:
                candidate_lock = self._locks.get(candidate_key)
                # Only evict if no lock exists or lock is not held
                if candidate_lock is None or not candidate_lock.locked():
                    self._buckets.pop(candidate_key, None)
                    self._locks.pop(candidate_key, None)
                    logger.debug("🧹 Evicted oldest rate limit bucket: %s", candidate_key)
                    evicted = True
                    break
            # If we couldn't evict (every bucket is locked = active traffic),
            # refuse to create a new one. The previous shared __overflow__
            # bucket let any caller drain tokens that should have belonged
            # to a different key — turning the safety valve into a global
            # DoS amplifier. We'd rather deny the request and signal
            # retry_after = the config's window.
            if not evicted:
                existing = self._buckets.get(key)
                if existing is not None:
                    return existing
                logger.warning(
                    "🧹 Rate limit bucket pool exhausted (count=%d, max=%d); "
                    "denying %s — caller should back off for one window.",
                    len(self._buckets),
                    self.MAX_BUCKETS,
                    key,
                )
                return None

        # Use setdefault for atomic get-or-create operation
        return self._buckets.setdefault(
            key,
            RateLimitBucket(
                tokens=float(config.requests),
                last_update=time.time(),
                window=config.window,
                max_tokens=config.requests,
            ),
        )

    async def check(
        self,
        config_name: str,
        user_id: int | None = None,
        channel_id: int | None = None,
        guild_id: int | None = None,
    ) -> tuple[bool, float, str | None]:
        """
        Check if action is allowed under rate limit.
        Uses per-bucket locks for better concurrency.

        Returns:
            (allowed, retry_after, message)
            - allowed: True if action is permitted
            - retry_after: Seconds to wait if not allowed
            - message: Cooldown message if not allowed
        """
        if config_name not in self._configs:
            # No config = no limit
            return True, 0.0, None

        config = self._configs[config_name]
        key = self._get_bucket_key(config_name, config, user_id, channel_id, guild_id)

        # Fast path: no allocation when the lock already exists.
        lock = self._locks.get(key)
        if lock is None:
            # Slow path: ``setdefault`` is dict-level atomic, so two
            # coroutines hitting a new key simultaneously share ONE lock
            # rather than racing past a ``not in`` check and both
            # consuming tokens under independent Lock objects. The
            # throwaway Lock() is one allocation per first-time miss
            # only — cheap.
            lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            bucket = self._get_or_create_bucket(key, config)
            if bucket is None:
                # Pool exhausted (see _get_or_create_bucket). Deny without
                # touching anyone else's tokens. retry_after is one full
                # window so the caller backs off long enough for some
                # bucket somewhere to free up.
                self._stats[config_name]["blocked"] += 1
                if config.silent:
                    # Honor silent configs here too — the normal deny path
                    # returns message=None for them, and callers post any
                    # non-None message to the channel.
                    msg = None
                elif config.cooldown_message:
                    msg = config.cooldown_message.format(retry=config.window)
                else:
                    msg = "Rate limiter overloaded — please retry shortly"
                return False, float(config.window), msg

            # Apply adaptive multiplier for adaptive configs
            if config.adaptive and self._adaptive_enabled:
                bucket.adaptive_multiplier = self._get_adaptive_multiplier()

            allowed, retry_after = bucket.consume()

            # Update stats
            if allowed:
                self._stats[config_name]["allowed"] += 1
            else:
                self._stats[config_name]["blocked"] += 1

            # Generate message
            message = None
            if not allowed and config.cooldown_message and not config.silent:
                message = config.cooldown_message.format(retry=retry_after)

            return allowed, retry_after, message

    async def is_allowed(
        self,
        config_name: str,
        user_id: int | None = None,
        channel_id: int | None = None,
        guild_id: int | None = None,
    ) -> bool:
        """Simple check - just returns True/False."""
        allowed, _, _ = await self.check(config_name, user_id, channel_id, guild_id)
        return allowed

    async def wait_for(
        self,
        config_name: str,
        user_id: int | None = None,
        channel_id: int | None = None,
        guild_id: int | None = None,
        max_wait: float = 60.0,
    ) -> bool:
        """
        Wait until rate limit allows action.
        Returns True if waited successfully, False if exceeded max_wait.
        """
        total_waited = 0.0

        while total_waited < max_wait:
            allowed, retry_after, _ = await self.check(config_name, user_id, channel_id, guild_id)

            if allowed:
                return True

            wait_time = min(retry_after, max_wait - total_waited)
            if wait_time <= 0:
                break

            await asyncio.sleep(wait_time)
            total_waited += wait_time

        return False

    def get_stats(self) -> dict[str, Any]:
        """Get rate limiting statistics."""
        # Deep-copy the inner per-config dicts so a caller mutating a returned
        # inner dict can't corrupt the live counters (dict(self._stats) alone is
        # a shallow copy that shares the inner dict objects).
        stats: dict[str, Any] = {k: dict(v) for k, v in self._stats.items()}
        # Add additional info
        stats["active_buckets"] = len(self._buckets)
        stats["total_blocked"] = sum(s.get("blocked", 0) for s in self._stats.values())
        return stats

    def reset_stats(self) -> None:
        """Reset statistics."""
        self._stats.clear()

    # ==================== Channel Rate Limit Methods ====================

    @staticmethod
    def channel_config_name(channel_id: int) -> str:
        """Config name for an owner-set per-channel limit."""
        return f"channel_custom:{channel_id}"

    def get_custom_channel_limit(self, channel_id: int) -> int | None:
        """The owner-set per-channel limit, or None when none is configured."""
        return self._channel_limits.get(channel_id)

    def get_channel_limit(self, channel_id: int) -> int:
        """Get current rate limit for a specific channel."""
        # Custom limit survives bucket eviction now — read the persistent map.
        custom = self._channel_limits.get(channel_id)
        if custom is not None:
            return custom
        # Return default. _setup_defaults always registers "gemini_api" and no
        # path deletes it, so the config is present; fall back to the shared
        # DEFAULT_GEMINI_RPM constant (not a stale literal) for total safety.
        gemini_config = self._configs.get("gemini_api")
        return gemini_config.requests if gemini_config else self.DEFAULT_GEMINI_RPM

    async def set_channel_limit(self, channel_id: int, requests_per_minute: int) -> None:
        """Set custom rate limit for a specific channel.

        Registers a PER-CHANNEL config (a single shared "channel_custom"
        config froze the FIRST channel's rpm into every later channel's
        bucket recreation) and records the limit in ``_channel_limits`` so
        bucket eviction can't erase it. Enforcement happens in ai_cog's
        rate-limit gauntlet via ``channel_config_name``.
        """
        config_name = self.channel_config_name(channel_id)
        self._channel_limits[channel_id] = requests_per_minute

        # Add or update config for this channel's limit
        self.add_config(
            config_name,
            RateLimitConfig(
                requests=requests_per_minute,
                window=60,
                limit_type=RateLimitType.CHANNEL,
                cooldown_message="⏳ Channel rate limit reached. Wait {retry:.1f}s",
            ),
        )

        # Update or create bucket under lock to prevent race conditions.
        # Use setdefault on the slow path so two simultaneous first-time
        # accesses share one Lock rather than racing past ``not in``.
        key = f"{config_name}:channel:{channel_id}"
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if key in self._buckets:
                self._buckets[key].max_tokens = requests_per_minute
                self._buckets[key].tokens = float(requests_per_minute)
            else:
                # Honor the same MAX_BUCKETS ceiling _get_or_create_bucket enforces
                # so this per-channel path can't push the pool past the cap.
                if len(self._buckets) >= self.MAX_BUCKETS:
                    logger.warning(
                        "🚦 Rate limit bucket pool full (max=%d); cannot set channel %d limit",
                        self.MAX_BUCKETS,
                        channel_id,
                    )
                    return
                self._buckets[key] = RateLimitBucket(
                    tokens=float(requests_per_minute),
                    last_update=time.time(),
                    window=60,
                    max_tokens=requests_per_minute,
                )

        logger.info("🚦 Set channel %d rate limit to %d/min", channel_id, requests_per_minute)

    def reload_limits(self) -> None:
        """Re-apply the built-in default configurations and refresh adaptive
        multipliers. (No file is read — this resets the default names back
        to their hardcoded values; runtime ``add_config`` overrides of those
        names are reset too.)"""
        try:
            # Re-setup defaults (in case config changed)
            self._setup_defaults()

            # Reconcile existing buckets to the (possibly restored) config
            # values. add_config only rewrites self._configs; live buckets
            # created earlier via setdefault keep their old max_tokens/window
            # and would refill toward a stale limit until age-eviction. Snapshot
            # via list() so a concurrent mutation can't raise "dictionary
            # changed size", mirroring update_all_adaptive_limits.
            for key, bucket in list(self._buckets.items()):
                config_name = self._config_name_from_key(key)
                config = self._configs.get(config_name)
                if config is None:
                    continue
                bucket.max_tokens = config.requests
                bucket.window = config.window
                # Clamp current tokens so a lowered limit takes effect
                # immediately rather than letting a pre-filled bucket overshoot.
                if bucket.tokens > config.requests:
                    bucket.tokens = float(config.requests)

            # Update adaptive multipliers
            if self._adaptive_enabled:
                self.update_all_adaptive_limits()

            logger.info("🔄 Rate limiter configurations reloaded")
        except Exception:
            logger.exception("Failed to reload rate limits")

    def _get_adaptive_multiplier(self) -> float:
        """
        Get rate limit multiplier based on circuit breaker state.

        Returns higher multiplier when circuit is healthy,
        lower when circuit is degraded or open.
        """
        if not CIRCUIT_BREAKER_AVAILABLE or gemini_circuit is None:
            return 1.0

        try:
            state = gemini_circuit.state.name
            return self.ADAPTIVE_MULTIPLIERS.get(state, 1.0)
        except Exception as e:
            logger.debug("Failed to get circuit breaker state: %s", e)
            return 1.0

    def update_all_adaptive_limits(self) -> None:
        """
        Update all adaptive buckets based on current circuit state.

        Call this periodically or when circuit state changes.
        """
        multiplier = self._get_adaptive_multiplier()

        # Snapshot via list() so a concurrent ``_get_or_create_bucket``
        # mutation can't raise ``RuntimeError: dictionary changed size``
        # mid-iteration.
        for key, bucket in list(self._buckets.items()):
            # Only update buckets for adaptive configs
            config_name = self._config_name_from_key(key)
            if config_name in self._configs:
                config = self._configs[config_name]
                if config.adaptive:
                    bucket.adaptive_multiplier = multiplier

        logger.debug("📊 Updated adaptive rate limits: multiplier=%.2f", multiplier)

    def set_adaptive_enabled(self, enabled: bool) -> None:
        """Enable or disable adaptive rate limiting."""
        self._adaptive_enabled = enabled
        if enabled:
            self.update_all_adaptive_limits()
        else:
            # Reset all multipliers to 1.0
            for bucket in self._buckets.values():
                bucket.adaptive_multiplier = 1.0
        logger.info("⏱️ Adaptive rate limiting: %s", "enabled" if enabled else "disabled")

    async def cleanup_old_buckets(self, max_age: float = 3600.0) -> int:
        """Remove buckets that haven't been used in max_age seconds.

        Thread-safe: Acquires lock before removing each bucket to ensure
        no concurrent operations are in progress.

        We deliberately DO NOT pop the per-key lock from _locks WHILE the
        bucket is being removed (see below). Doing so during the remove
        introduced a race: a coroutine that already grabbed the lock via
        ``setdefault`` would keep running with the old object while a
        concurrent caller would call ``setdefault`` after the pop and get
        a fresh, unrelated lock — two callers ended up inside the critical
        section under different locks.

        However, after the per-bucket remove pass, we sweep ``_locks`` for
        keys that no longer have a corresponding bucket and drop those
        unused lock objects. This avoids an unbounded leak of asyncio.Lock
        objects (one per ever-seen key), which would otherwise accumulate
        forever during long-running processes with churning bucket keys.
        """
        now = time.time()
        removed = 0

        # Collect keys to remove first (snapshot of items)
        keys_to_remove = [
            key for key, bucket in list(self._buckets.items()) if now - bucket.last_update > max_age
        ]

        # Remove buckets atomically per key (locks stay during this pass —
        # see docstring; locks are swept *after* this loop completes).
        for key in keys_to_remove:
            lock = self._locks.get(key)
            if lock:
                async with lock:
                    bucket = self._buckets.get(key)
                    if bucket and now - bucket.last_update > max_age:
                        self._buckets.pop(key, None)
                        removed += 1
            else:
                # No lock means no concurrent operations - safe to remove
                self._buckets.pop(key, None)
                removed += 1

        # Sweep orphaned locks (no corresponding bucket). Skip locks that
        # are currently held — a caller may be inside the critical section
        # right now and removing the lock would let a concurrent
        # ``setdefault`` install a fresh, unrelated lock and double-enter
        # the section.
        for k in list(self._locks):
            if k not in self._buckets:
                lock = self._locks.get(k)
                if lock is None or not lock.locked():
                    self._locks.pop(k, None)

        if removed > 0:
            logger.info("🧹 Cleaned up %d old rate limit buckets", removed)

        return removed

    def start_cleanup_task(self, interval: float = 1800.0) -> None:
        """Start background task to periodically clean up old buckets."""

        async def _cleanup_loop():
            while True:
                try:
                    await asyncio.sleep(interval)
                    await self.cleanup_old_buckets()
                except asyncio.CancelledError:
                    break
                except Exception:
                    # One failed pass must not kill bucket/lock cleanup for
                    # the life of the process (the task is fire-and-forget,
                    # so the exception would otherwise vanish unobserved).
                    logger.exception("rate-limiter cleanup pass failed; retrying next interval")

        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(_cleanup_loop())

    async def stop_cleanup_task(self) -> None:
        """Stop the cleanup background task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task


# Global rate limiter instance
rate_limiter = RateLimiter()


# ==================== Decorators ====================


def ratelimit(
    config_name: str = "command", *, send_message: bool = True, delete_after: float | None = 5.0
):
    """
    Decorator for rate limiting Discord commands.

    Usage:
        @bot.command()
        @ratelimit("music_command")
        async def play(ctx, url: str):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(self_or_ctx, *args, **kwargs):
            # Handle both cog methods and standalone commands
            if isinstance(self_or_ctx, commands.Context):
                ctx = self_or_ctx
                cog = None
            else:
                cog = self_or_ctx
                # pop (not get): leaving ctx in kwargs while also passing it
                # positionally below raises "got multiple values for 'ctx'".
                ctx = args[0] if args else kwargs.pop("ctx", None)
                args = args[1:] if args else args

            if ctx is None:
                return await func(self_or_ctx, *args, **kwargs)

            # Check rate limit
            allowed, _retry_after, message = await rate_limiter.check(
                config_name,
                user_id=ctx.author.id,
                channel_id=ctx.channel.id,
                guild_id=ctx.guild.id if ctx.guild else None,
            )

            if not allowed:
                if send_message and message and delete_after is not None:
                    with contextlib.suppress(discord.HTTPException):
                        await ctx.send(message, delete_after=delete_after)
                elif send_message and message:
                    with contextlib.suppress(discord.HTTPException):
                        await ctx.send(message)
                return None

            # Execute command
            if cog:
                return await func(cog, ctx, *args, **kwargs)
            else:
                return await func(ctx, *args, **kwargs)

        return wrapper

    return decorator


def ai_ratelimit(
    per_user: bool = True,
    per_guild: bool = True,
    check_global: bool = True,
    send_message: bool = True,
):
    """
    Specialized decorator for AI/Gemini rate limiting.
    Checks per-user, per-guild, and global limits.

    Usage:
        @ai_ratelimit()
        async def process_ai_message(self, message):
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract context from args
            # Could be (self, message), (self, ctx), etc.
            message_or_ctx = None
            for arg in args:
                if isinstance(arg, discord.Message | commands.Context):
                    message_or_ctx = arg
                    break

            if message_or_ctx is None:
                return await func(*args, **kwargs)

            # Get IDs and send function
            user_id = message_or_ctx.author.id
            channel_id = message_or_ctx.channel.id
            guild_id = message_or_ctx.guild.id if message_or_ctx.guild else None
            # Always use channel.send for consistency (works for both Message and Context)
            send_func = message_or_ctx.channel.send

            # Check MOST-SPECIFIC first. token-bucket consume() is
            # destructive: widest-first meant a request denied by the
            # per-user limit had already burned a shared-global and a guild
            # token, so one user-limited spammer drained the global budget
            # for everyone.
            if per_user:
                allowed, _retry, msg = await rate_limiter.check(
                    "ai_user", user_id=user_id, channel_id=channel_id
                )
                if not allowed:
                    if send_message and msg:
                        with contextlib.suppress(discord.HTTPException):
                            await send_func(msg, delete_after=10)
                    return None

            # Check per-guild limit
            if per_guild and guild_id:
                allowed, _retry, msg = await rate_limiter.check("ai_guild", guild_id=guild_id)
                if not allowed:
                    if send_message and msg:
                        with contextlib.suppress(discord.HTTPException):
                            await send_func(msg, delete_after=10)
                    return None

            # Check global limit last
            if check_global:
                allowed, _retry, msg = await rate_limiter.check("gemini_global", guild_id=guild_id)
                if not allowed:
                    if send_message and msg:
                        with contextlib.suppress(discord.HTTPException):
                            await send_func(msg, delete_after=10)
                    return None

            return await func(*args, **kwargs)

        return wrapper

    return decorator


# ==================== Utility Functions ====================


async def check_rate_limit(
    config_name: str,
    ctx_or_message: commands.Context | discord.Message,
    send_message: bool = True,
    delete_after: float = 5.0,
) -> bool:
    """
    Helper function to check rate limit for a context or message.

    Usage:
        if not await check_rate_limit("gemini_api", ctx):
            return
    """
    # Get IDs - works for both Message and Context
    user_id = ctx_or_message.author.id
    channel_id = ctx_or_message.channel.id
    guild_id = ctx_or_message.guild.id if ctx_or_message.guild else None
    # Always use channel.send for consistency
    send_func = ctx_or_message.channel.send

    allowed, _retry_after, message = await rate_limiter.check(
        config_name, user_id=user_id, channel_id=channel_id, guild_id=guild_id
    )

    if not allowed and send_message and message:
        with contextlib.suppress(discord.HTTPException):
            await send_func(message, delete_after=delete_after)

    return allowed


def format_rate_limit_stats() -> str:
    """Format rate limit statistics as a string."""
    stats = rate_limiter.get_stats()
    if not stats:
        return "No rate limit data yet."

    lines = ["📊 **Rate Limit Statistics**\n"]
    for name, data in sorted(stats.items()):
        # Skip non-dict items (active_buckets, total_blocked are ints)
        if not isinstance(data, dict):
            continue
        total = data["allowed"] + data["blocked"]
        if total > 0:
            block_rate = (data["blocked"] / total) * 100
            lines.append(
                f"• **{name}**: {data['allowed']} allowed, "
                f"{data['blocked']} blocked ({block_rate:.1f}% blocked)"
            )

    return "\n".join(lines)
