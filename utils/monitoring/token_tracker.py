"""
Token Usage Tracker for Discord Bot.
Tracks token usage per user, channel, and provides analytics.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class TokenUsage:
    """Token usage data for a single period."""

    input_tokens: int = 0
    output_tokens: int = 0
    request_count: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def add(self, input_tokens: int, output_tokens: int) -> None:
        """Add token usage."""
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.request_count += 1


@dataclass
class UserTokenStats:
    """Token statistics for a user."""

    user_id: int
    total_input: int = 0
    total_output: int = 0
    total_requests: int = 0
    hourly_usage: dict[str, TokenUsage] = field(default_factory=dict)
    daily_usage: dict[str, TokenUsage] = field(default_factory=dict)
    first_use: float = field(default_factory=time.time)
    last_use: float = field(default_factory=time.time)

    @property
    def total_tokens(self) -> int:
        return self.total_input + self.total_output

    @property
    def average_per_request(self) -> float:
        if self.total_requests == 0:
            return 0
        return self.total_tokens / self.total_requests


class TokenTracker:
    """
    Tracks token usage per user and provides analytics.

    Usage:
        tracker = TokenTracker()

        # Record usage
        tracker.record(user_id=123, input_tokens=500, output_tokens=150)

        # Get stats
        stats = tracker.get_user_stats(123)
        print(f"Total tokens: {stats.total_tokens}")

        # Get top users
        top_users = tracker.get_top_users(limit=10)
    """

    def __init__(self, max_history_days: int = 30):
        self._user_stats: dict[int, UserTokenStats] = {}
        self._channel_usage: dict[int, TokenUsage] = defaultdict(TokenUsage)
        self._global_usage = TokenUsage()
        self._max_history_days = max_history_days
        self.logger = logging.getLogger("TokenTracker")

    def record(
        self, user_id: int, input_tokens: int, output_tokens: int, channel_id: int | None = None
    ) -> None:
        """Record token usage for a user."""
        now = time.time()
        hour_key = datetime.now().strftime("%Y-%m-%d-%H")
        day_key = datetime.now().strftime("%Y-%m-%d")

        # Initialize user stats if needed
        if user_id not in self._user_stats:
            self._user_stats[user_id] = UserTokenStats(user_id=user_id)

        stats = self._user_stats[user_id]

        # Update totals
        stats.total_input += input_tokens
        stats.total_output += output_tokens
        stats.total_requests += 1
        stats.last_use = now

        # Update hourly usage
        if hour_key not in stats.hourly_usage:
            stats.hourly_usage[hour_key] = TokenUsage()
        stats.hourly_usage[hour_key].add(input_tokens, output_tokens)

        # Update daily usage
        if day_key not in stats.daily_usage:
            stats.daily_usage[day_key] = TokenUsage()
        stats.daily_usage[day_key].add(input_tokens, output_tokens)

        # Update channel usage
        if channel_id:
            self._channel_usage[channel_id].add(input_tokens, output_tokens)

        # Update global usage
        self._global_usage.add(input_tokens, output_tokens)

        self.logger.debug(
            "Recorded tokens for user %d: +%d input, +%d output",
            user_id,
            input_tokens,
            output_tokens,
        )

    def get_user_stats(self, user_id: int) -> UserTokenStats | None:
        """Get token stats for a specific user."""
        return self._user_stats.get(user_id)

    def get_top_users(self, limit: int = 10) -> list[tuple[int, UserTokenStats]]:
        """Get top users by total token usage."""
        sorted_users = sorted(
            self._user_stats.items(), key=lambda x: x[1].total_tokens, reverse=True
        )
        return sorted_users[:limit]

    def get_channel_stats(self, channel_id: int) -> TokenUsage:
        """Get token stats for a channel."""
        return self._channel_usage.get(channel_id, TokenUsage())

    def get_global_stats(self) -> dict[str, Any]:
        """Get global token usage statistics."""
        return {
            "total_input_tokens": self._global_usage.input_tokens,
            "total_output_tokens": self._global_usage.output_tokens,
            "total_tokens": self._global_usage.total_tokens,
            "total_requests": self._global_usage.request_count,
            "unique_users": len(self._user_stats),
            "avg_tokens_per_request": (
                self._global_usage.total_tokens / max(1, self._global_usage.request_count)
            ),
        }

    def get_daily_summary(self, days: int = 7) -> list[dict[str, Any]]:
        """Get daily token usage summary."""
        summaries = []

        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            day_key = date.strftime("%Y-%m-%d")

            daily_total = TokenUsage()
            for stats in self._user_stats.values():
                if day_key in stats.daily_usage:
                    usage = stats.daily_usage[day_key]
                    daily_total.input_tokens += usage.input_tokens
                    daily_total.output_tokens += usage.output_tokens
                    daily_total.request_count += usage.request_count

            summaries.append(
                {
                    "date": day_key,
                    "input_tokens": daily_total.input_tokens,
                    "output_tokens": daily_total.output_tokens,
                    "total_tokens": daily_total.total_tokens,
                    "requests": daily_total.request_count,
                }
            )

        return summaries

    def cleanup_old_data(self) -> int:
        """Remove usage data older than max_history_days."""
        cutoff = datetime.now() - timedelta(days=self._max_history_days)
        cutoff_key = cutoff.strftime("%Y-%m-%d")
        removed = 0

        for stats in self._user_stats.values():
            # Clean hourly data
            old_hours = [k for k in stats.hourly_usage if k < cutoff_key]
            for k in old_hours:
                del stats.hourly_usage[k]
                removed += 1

            # Clean daily data
            old_days = [k for k in stats.daily_usage if k < cutoff_key]
            for k in old_days:
                del stats.daily_usage[k]
                removed += 1

        if removed > 0:
            self.logger.info("Cleaned up %d old token records", removed)

        return removed

    def export_stats(self) -> dict[str, Any]:
        """Export all stats for persistence."""
        return {
            "global": self.get_global_stats(),
            "daily_summary": self.get_daily_summary(30),
            "top_users": [
                {
                    "user_id": uid,
                    "total_tokens": stats.total_tokens,
                    "requests": stats.total_requests,
                }
                for uid, stats in self.get_top_users(50)
            ],
        }


# Global token tracker instance
token_tracker = TokenTracker()


def record_token_usage(
    user_id: int, input_tokens: int, output_tokens: int, channel_id: int | None = None
) -> None:
    """Convenience function to record token usage."""
    token_tracker.record(user_id, input_tokens, output_tokens, channel_id)
