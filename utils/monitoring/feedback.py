"""
Feedback Collection System for Discord Bot.
Collects user feedback via reactions and provides analytics.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import discord


class FeedbackType(Enum):
    """Types of feedback reactions."""

    POSITIVE = "positive"  # 👍 ✅ ❤️
    NEGATIVE = "negative"  # 👎 ❌
    NEUTRAL = "neutral"  # 🤔
    HELPFUL = "helpful"  # 💡
    FUNNY = "funny"  # 😂
    LENGTH_TOO_SHORT = "too_short"  # 📏
    LENGTH_TOO_LONG = "too_long"  # 📜


# Reaction to feedback type mapping
REACTION_MAP = {
    "👍": FeedbackType.POSITIVE,
    "✅": FeedbackType.POSITIVE,
    "❤️": FeedbackType.POSITIVE,
    "💖": FeedbackType.POSITIVE,
    "👎": FeedbackType.NEGATIVE,
    "❌": FeedbackType.NEGATIVE,
    "🤔": FeedbackType.NEUTRAL,
    "💡": FeedbackType.HELPFUL,
    "😂": FeedbackType.FUNNY,
    "📏": FeedbackType.LENGTH_TOO_SHORT,
    "📜": FeedbackType.LENGTH_TOO_LONG,
}


@dataclass
class FeedbackEntry:
    """A single feedback entry."""

    message_id: int
    channel_id: int
    user_id: int
    feedback_type: FeedbackType
    timestamp: float = field(default_factory=time.time)
    context: str | None = None  # First 100 chars of AI response


@dataclass
class FeedbackStats:
    """Aggregated feedback statistics."""

    total_feedback: int = 0
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    helpful_count: int = 0
    funny_count: int = 0

    @property
    def satisfaction_rate(self) -> float:
        """Calculate satisfaction rate (positive / total)."""
        if self.total_feedback == 0:
            return 0
        return self.positive_count / self.total_feedback

    @property
    def negative_rate(self) -> float:
        """Calculate negative rate."""
        if self.total_feedback == 0:
            return 0
        return self.negative_count / self.total_feedback


class FeedbackCollector:
    """
    Collects and analyzes user feedback on AI responses.

    Usage:
        collector = FeedbackCollector()

        # Track a message for feedback
        collector.track_message(message_id, channel_id)

        # Process reaction (call from on_reaction_add)
        collector.process_reaction(message_id, user_id, emoji)

        # Get stats
        stats = collector.get_stats()
        print(f"Satisfaction: {stats.satisfaction_rate:.1%}")
    """

    # Maximum feedback entries to keep in memory
    MAX_FEEDBACK_ENTRIES = 10000

    def __init__(self, max_tracked_messages: int = 1000):
        self._tracked_messages: dict[int, dict] = {}  # message_id -> metadata
        self._feedback: list[FeedbackEntry] = []
        self._max_tracked = max_tracked_messages
        self._callbacks: list[Callable[[FeedbackEntry], None]] = []
        self.logger = logging.getLogger("FeedbackCollector")

    def track_message(
        self, message_id: int, channel_id: int, response_preview: str | None = None
    ) -> None:
        """Track a message for feedback collection."""
        # Cleanup old tracked messages if needed
        if len(self._tracked_messages) >= self._max_tracked:
            oldest = min(self._tracked_messages.keys())
            del self._tracked_messages[oldest]

        self._tracked_messages[message_id] = {
            "channel_id": channel_id,
            "timestamp": time.time(),
            "preview": response_preview[:100] if response_preview else None,
        }

    def is_tracked(self, message_id: int) -> bool:
        """Check if a message is being tracked."""
        return message_id in self._tracked_messages

    def process_reaction(self, message_id: int, user_id: int, emoji: str) -> FeedbackEntry | None:
        """Process a reaction and record feedback if applicable."""
        # Check if message is tracked
        if message_id not in self._tracked_messages:
            return None

        # Check if emoji is a feedback reaction
        if emoji not in REACTION_MAP:
            return None

        metadata = self._tracked_messages[message_id]
        feedback_type = REACTION_MAP[emoji]

        # Create feedback entry
        entry = FeedbackEntry(
            message_id=message_id,
            channel_id=metadata["channel_id"],
            user_id=user_id,
            feedback_type=feedback_type,
            context=metadata.get("preview"),
        )

        self._feedback.append(entry)

        # Cleanup old entries to prevent memory growth
        if len(self._feedback) > self.MAX_FEEDBACK_ENTRIES:
            self._feedback = self._feedback[-self.MAX_FEEDBACK_ENTRIES:]

        self.logger.info(
            "Recorded %s feedback from user %d on message %d",
            feedback_type.value,
            user_id,
            message_id,
        )

        # Trigger callbacks
        for callback in self._callbacks:
            try:
                callback(entry)
            except Exception as e:
                self.logger.error("Feedback callback error: %s", e)

        return entry

    def on_feedback(self, callback: Callable[[FeedbackEntry], None]) -> None:
        """Register a callback for new feedback."""
        self._callbacks.append(callback)

    def get_stats(self, hours: int | None = None) -> FeedbackStats:
        """Get aggregated feedback statistics."""
        stats = FeedbackStats()

        cutoff = 0
        if hours:
            cutoff = time.time() - (hours * 3600)

        for entry in self._feedback:
            if entry.timestamp < cutoff:
                continue

            stats.total_feedback += 1

            if entry.feedback_type == FeedbackType.POSITIVE:
                stats.positive_count += 1
            elif entry.feedback_type == FeedbackType.NEGATIVE:
                stats.negative_count += 1
            elif entry.feedback_type == FeedbackType.NEUTRAL:
                stats.neutral_count += 1
            elif entry.feedback_type == FeedbackType.HELPFUL:
                stats.helpful_count += 1
            elif entry.feedback_type == FeedbackType.FUNNY:
                stats.funny_count += 1

        return stats

    def get_recent_negative(self, limit: int = 10) -> list[FeedbackEntry]:
        """Get recent negative feedback for review."""
        negative = [f for f in self._feedback if f.feedback_type == FeedbackType.NEGATIVE]
        return sorted(negative, key=lambda x: x.timestamp, reverse=True)[:limit]

    def get_channel_stats(self, channel_id: int) -> FeedbackStats:
        """Get stats for a specific channel."""
        channel_feedback = [f for f in self._feedback if f.channel_id == channel_id]

        stats = FeedbackStats()
        for entry in channel_feedback:
            stats.total_feedback += 1
            if entry.feedback_type == FeedbackType.POSITIVE:
                stats.positive_count += 1
            elif entry.feedback_type == FeedbackType.NEGATIVE:
                stats.negative_count += 1

        return stats

    def export_stats(self) -> dict[str, Any]:
        """Export statistics for reporting."""
        stats = self.get_stats()
        return {
            "total_feedback": stats.total_feedback,
            "satisfaction_rate": f"{stats.satisfaction_rate:.1%}",
            "positive": stats.positive_count,
            "negative": stats.negative_count,
            "neutral": stats.neutral_count,
            "helpful": stats.helpful_count,
            "funny": stats.funny_count,
            "recent_negative": [
                {
                    "message_id": f.message_id,
                    "context": f.context,
                }
                for f in self.get_recent_negative(5)
            ],
        }


# Global feedback collector instance
feedback_collector = FeedbackCollector()


async def add_feedback_reactions(message: discord.Message) -> None:
    """Add feedback reaction options to a message."""
    reactions = ["👍", "👎", "💡"]
    for emoji in reactions:
        with contextlib.suppress(discord.HTTPException):
            await message.add_reaction(emoji)
