"""
AI Analytics Module
Tracks and analyzes AI interaction patterns.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# Try to import database
try:
    from utils.database import db

    DB_AVAILABLE = True
except ImportError:
    DB_AVAILABLE = False


@dataclass
class InteractionLog:
    """A single AI interaction log entry."""

    user_id: int
    channel_id: int
    guild_id: int | None
    input_length: int
    output_length: int
    response_time_ms: float
    intent: str
    model: str
    tool_calls: int = 0
    cache_hit: bool = False
    error: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class AnalyticsSummary:
    """Summary of AI analytics."""

    total_interactions: int
    avg_response_time_ms: float
    cache_hit_rate: float
    top_intents: list[tuple[str, int]]
    error_rate: float
    interactions_per_hour: float
    total_input_tokens: int
    total_output_tokens: int


@dataclass
class ResponseQuality:
    """Quality metrics for a single response."""

    score: float  # 0.0 to 1.0
    retry_count: int = 0
    was_edited: bool = False
    user_reaction: str | None = None  # 👍, 👎, ❓
    guardrail_triggered: bool = False
    response_length: int = 0
    factors: dict = field(default_factory=dict)


class AIAnalytics:
    """
    Tracks AI interactions for analysis and optimization.

    Features:
    - Response time tracking
    - Intent distribution analysis
    - Token usage monitoring
    - Error rate tracking
    - Cache effectiveness
    """

    # Token estimation (rough)
    CHARS_PER_TOKEN = 4

    # Limits to prevent memory growth
    MAX_HOURLY_KEYS = 168  # 7 days of hourly data
    MAX_INTENT_KEYS = 100  # Limit unique intents tracked

    def __init__(self):
        self.logger = logging.getLogger("AIAnalytics")

        # In-memory stats for quick access
        self._stats = {
            "total_interactions": 0,
            "total_response_time_ms": 0,
            "cache_hits": 0,
            "errors": 0,
            "intent_counts": defaultdict(int),
            "hourly_counts": defaultdict(int),
            "total_input_chars": 0,
            "total_output_chars": 0,
        }

        self._start_time = time.time()

    async def log_interaction(
        self,
        user_id: int,
        channel_id: int,
        guild_id: int | None,
        input_text: str,
        output_text: str,
        response_time_ms: float,
        intent: str = "unknown",
        model: str = "gemini",
        tool_calls: int = 0,
        cache_hit: bool = False,
        error: str | None = None,
    ) -> None:
        """
        Log an AI interaction.

        Args:
            user_id: Discord user ID
            channel_id: Discord channel ID
            guild_id: Discord guild ID (None for DMs)
            input_text: User's input message
            output_text: AI's response
            response_time_ms: Time taken to generate response
            intent: Detected intent category
            model: AI model used
            tool_calls: Number of tool/function calls
            cache_hit: Whether response was from cache
            error: Error message if failed
        """
        # Update in-memory stats
        self._stats["total_interactions"] += 1
        self._stats["total_response_time_ms"] += response_time_ms
        self._stats["intent_counts"][intent] += 1
        self._stats["total_input_chars"] += len(input_text)
        self._stats["total_output_chars"] += len(output_text)

        if cache_hit:
            self._stats["cache_hits"] += 1
        if error:
            self._stats["errors"] += 1

        # Track hourly (with cleanup to prevent unbounded growth)
        hour_key = datetime.now().strftime("%Y-%m-%d-%H")
        self._stats["hourly_counts"][hour_key] += 1

        # Cleanup old hourly keys if too many
        if len(self._stats["hourly_counts"]) > self.MAX_HOURLY_KEYS:
            sorted_keys = sorted(self._stats["hourly_counts"].keys())
            keys_to_remove = sorted_keys[: len(sorted_keys) - self.MAX_HOURLY_KEYS]
            for key in keys_to_remove:
                del self._stats["hourly_counts"][key]

        # Limit intent_counts growth
        if len(self._stats["intent_counts"]) > self.MAX_INTENT_KEYS:
            # Keep top intents by count
            sorted_intents = sorted(
                self._stats["intent_counts"].items(), key=lambda x: x[1], reverse=True
            )
            self._stats["intent_counts"] = defaultdict(
                int, dict(sorted_intents[: self.MAX_INTENT_KEYS])
            )

        # Log to database if available
        if DB_AVAILABLE:
            try:
                await self._save_to_db(
                    user_id=user_id,
                    channel_id=channel_id,
                    guild_id=guild_id,
                    input_length=len(input_text),
                    output_length=len(output_text),
                    response_time_ms=response_time_ms,
                    intent=intent,
                    model=model,
                    tool_calls=tool_calls,
                    cache_hit=cache_hit,
                    error=error,
                )
            except Exception as e:
                self.logger.debug("Failed to save analytics to DB: %s", e)

    async def _save_to_db(self, **kwargs) -> None:
        """Save interaction to database."""
        async with db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO ai_analytics
                (user_id, channel_id, guild_id, input_length, output_length,
                 response_time_ms, intent, model, tool_calls, cache_hit, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    kwargs["user_id"],
                    kwargs["channel_id"],
                    kwargs["guild_id"],
                    kwargs["input_length"],
                    kwargs["output_length"],
                    kwargs["response_time_ms"],
                    kwargs["intent"],
                    kwargs["model"],
                    kwargs["tool_calls"],
                    kwargs["cache_hit"],
                    kwargs["error"],
                ),
            )

    def calculate_quality_score(
        self,
        response: str,
        retry_count: int = 0,
        was_edited: bool = False,
        user_reaction: str | None = None,
        guardrail_triggered: bool = False,
    ) -> ResponseQuality:
        """
        Calculate quality score for an AI response.

        Scoring factors:
        - Base score: 1.0
        - Retry penalty: -0.1 per retry (max -0.3)
        - Edit penalty: -0.2
        - User reaction: 👍 +0.1, 👎 -0.3, ❓ -0.1
        - Guardrail trigger: -0.2
        - Very short response: -0.1

        Args:
            response: The AI response text
            retry_count: Number of retries needed
            was_edited: Whether the response was edited/regenerated
            user_reaction: User's reaction emoji
            guardrail_triggered: Whether a guardrail was triggered

        Returns:
            ResponseQuality with calculated score and factors
        """
        score = 1.0
        factors = {}

        # Retry penalty
        if retry_count > 0:
            penalty = min(0.3, retry_count * 0.1)
            score -= penalty
            factors["retry_penalty"] = -penalty

        # Edit penalty
        if was_edited:
            score -= 0.2
            factors["edit_penalty"] = -0.2

        # User reaction
        if user_reaction == "👍":
            score += 0.1
            factors["positive_reaction"] = 0.1
        elif user_reaction == "👎":
            score -= 0.3
            factors["negative_reaction"] = -0.3
        elif user_reaction == "❓":
            score -= 0.1
            factors["confusion_reaction"] = -0.1

        # Guardrail penalty
        if guardrail_triggered:
            score -= 0.2
            factors["guardrail_penalty"] = -0.2

        # Very short response penalty
        if len(response) < 20:
            score -= 0.1
            factors["short_response"] = -0.1

        # Clamp to 0.0-1.0
        score = max(0.0, min(1.0, score))

        return ResponseQuality(
            score=score,
            retry_count=retry_count,
            was_edited=was_edited,
            user_reaction=user_reaction,
            guardrail_triggered=guardrail_triggered,
            response_length=len(response),
            factors=factors,
        )

    def log_response_quality(self, quality: ResponseQuality, channel_id: int | None = None) -> None:
        """
        Log response quality metrics.

        Updates in-memory quality stats for aggregation.

        Args:
            quality: ResponseQuality object
            channel_id: Optional channel ID for per-channel tracking
        """
        # Initialize quality stats if needed
        if "quality_scores" not in self._stats:
            self._stats["quality_scores"] = []
            self._stats["quality_sum"] = 0.0
            self._stats["quality_count"] = 0
            self._stats["positive_reactions"] = 0
            self._stats["negative_reactions"] = 0

        # Update stats
        self._stats["quality_scores"].append(quality.score)
        self._stats["quality_sum"] += quality.score
        self._stats["quality_count"] += 1

        if quality.user_reaction == "👍":
            self._stats["positive_reactions"] += 1
        elif quality.user_reaction == "👎":
            self._stats["negative_reactions"] += 1

        # Keep only last 1000 scores for memory efficiency
        if len(self._stats["quality_scores"]) > 1000:
            removed = self._stats["quality_scores"].pop(0)
            self._stats["quality_sum"] -= removed
            self._stats["quality_count"] = len(self._stats["quality_scores"])

        self.logger.debug("📊 Quality logged: %.2f (factors: %s)", quality.score, quality.factors)

    def get_quality_summary(self) -> dict:
        """Get summary of quality metrics."""
        if "quality_count" not in self._stats or self._stats["quality_count"] == 0:
            return {
                "average_score": 0.0,
                "total_ratings": 0,
                "positive_reactions": 0,
                "negative_reactions": 0,
            }

        return {
            "average_score": self._stats["quality_sum"] / self._stats["quality_count"],
            "total_ratings": self._stats["quality_count"],
            "positive_reactions": self._stats.get("positive_reactions", 0),
            "negative_reactions": self._stats.get("negative_reactions", 0),
        }

    def get_summary(self) -> AnalyticsSummary:
        """Get summary of all analytics."""
        total = self._stats["total_interactions"]

        if total == 0:
            return AnalyticsSummary(
                total_interactions=0,
                avg_response_time_ms=0,
                cache_hit_rate=0,
                top_intents=[],
                error_rate=0,
                interactions_per_hour=0,
                total_input_tokens=0,
                total_output_tokens=0,
            )

        # Calculate averages
        avg_response = self._stats["total_response_time_ms"] / total
        cache_rate = self._stats["cache_hits"] / total
        error_rate = self._stats["errors"] / total

        # Get top intents
        intent_items = list(self._stats["intent_counts"].items())
        top_intents = sorted(intent_items, key=lambda x: x[1], reverse=True)[:5]

        # Calculate interactions per hour
        uptime_hours = (time.time() - self._start_time) / 3600
        per_hour = total / uptime_hours if uptime_hours > 0 else 0

        # Estimate tokens
        input_tokens = self._stats["total_input_chars"] // self.CHARS_PER_TOKEN
        output_tokens = self._stats["total_output_chars"] // self.CHARS_PER_TOKEN

        return AnalyticsSummary(
            total_interactions=total,
            avg_response_time_ms=round(avg_response, 2),
            cache_hit_rate=round(cache_rate, 3),
            top_intents=top_intents,
            error_rate=round(error_rate, 3),
            interactions_per_hour=round(per_hour, 2),
            total_input_tokens=input_tokens,
            total_output_tokens=output_tokens,
        )

    async def get_user_stats(self, user_id: int) -> dict[str, Any]:
        """Get statistics for a specific user."""
        if not DB_AVAILABLE:
            return {"error": "Database not available"}

        async with db.get_connection() as conn:
            # Total interactions
            cursor = await conn.execute(
                "SELECT COUNT(*) FROM ai_analytics WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            total = row[0] if row else 0

            # Average response time
            cursor = await conn.execute(
                "SELECT AVG(response_time_ms) FROM ai_analytics WHERE user_id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            avg_time = row[0] if row and row[0] else 0

            # Top intents
            cursor = await conn.execute(
                """
                SELECT intent, COUNT(*) as cnt
                FROM ai_analytics
                WHERE user_id = ?
                GROUP BY intent
                ORDER BY cnt DESC
                LIMIT 5
            """,
                (user_id,),
            )
            intents = await cursor.fetchall()

        return {
            "user_id": user_id,
            "total_interactions": total,
            "avg_response_time_ms": round(avg_time, 2),
            "top_intents": [(r[0], r[1]) for r in intents],
        }

    async def get_hourly_trend(self, hours: int = 24) -> list[tuple[str, int]]:
        """Get interaction counts by hour."""
        if not DB_AVAILABLE:
            # Use in-memory data
            now = datetime.now()
            result = []
            for i in range(hours - 1, -1, -1):
                hour = now - timedelta(hours=i)
                key = hour.strftime("%Y-%m-%d-%H")
                count = self._stats["hourly_counts"].get(key, 0)
                result.append((key, count))
            return result

        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT strftime('%Y-%m-%d-%H', created_at) as hour, COUNT(*)
                FROM ai_analytics
                WHERE created_at >= datetime('now', ?)
                GROUP BY hour
                ORDER BY hour
            """,
                (f"-{hours} hours",),
            )
            rows = await cursor.fetchall()

        return [(r[0], r[1]) for r in rows]

    def get_realtime_stats(self) -> dict[str, Any]:
        """Get real-time statistics (in-memory only)."""
        summary = self.get_summary()
        return {
            "total": summary.total_interactions,
            "avg_response_ms": summary.avg_response_time_ms,
            "cache_hit_rate": f"{summary.cache_hit_rate:.1%}",
            "error_rate": f"{summary.error_rate:.1%}",
            "per_hour": summary.interactions_per_hour,
            "top_intent": summary.top_intents[0][0] if summary.top_intents else "N/A",
            "tokens_estimate": {
                "input": summary.total_input_tokens,
                "output": summary.total_output_tokens,
            },
        }

    def reset_stats(self) -> None:
        """Reset in-memory statistics."""
        self._stats = {
            "total_interactions": 0,
            "total_response_time_ms": 0,
            "cache_hits": 0,
            "errors": 0,
            "intent_counts": defaultdict(int),
            "hourly_counts": defaultdict(int),
            "total_input_chars": 0,
            "total_output_chars": 0,
            "response_times": [],  # For percentile calculation
            "intent_feedback": [],  # For accuracy tracking
        }
        self._start_time = time.time()

    def _record_response_time(self, response_time_ms: float) -> None:
        """Record response time for percentile calculation."""
        if "response_times" not in self._stats:
            self._stats["response_times"] = []

        self._stats["response_times"].append(response_time_ms)

        # Keep only last 1000 for memory efficiency
        if len(self._stats["response_times"]) > 1000:
            self._stats["response_times"] = self._stats["response_times"][-1000:]

    def get_latency_percentiles(self, period: str = "all") -> dict:
        """
        Get latency percentiles (p50, p95, p99).

        Args:
            period: Time period ("all", "hour", "day") - currently only "all" supported

        Returns:
            Dictionary with p50, p95, p99 values in milliseconds
        """
        response_times = self._stats.get("response_times", [])

        if not response_times:
            return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "count": 0}

        # Sort for percentile calculation
        sorted_times = sorted(response_times)
        n = len(sorted_times)

        def percentile(p: float) -> float:
            """Calculate percentile value."""
            idx = int(n * p / 100)
            idx = min(idx, n - 1)
            return sorted_times[idx]

        return {
            "p50": round(percentile(50), 2),
            "p95": round(percentile(95), 2),
            "p99": round(percentile(99), 2),
            "count": n,
            "min": round(min(sorted_times), 2),
            "max": round(max(sorted_times), 2),
        }

    def record_intent_feedback(
        self, detected_intent: str, actual_intent: str, user_id: int | None = None
    ) -> None:
        """
        Record intent detection feedback for accuracy analysis.

        Args:
            detected_intent: What the system detected
            actual_intent: What the correct intent was (from user feedback)
            user_id: Optional user ID for per-user accuracy tracking
        """
        if "intent_feedback" not in self._stats:
            self._stats["intent_feedback"] = []

        self._stats["intent_feedback"].append(
            {
                "detected": detected_intent,
                "actual": actual_intent,
                "correct": detected_intent == actual_intent,
                "user_id": user_id,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Keep only last 500 feedback entries
        if len(self._stats["intent_feedback"]) > 500:
            self._stats["intent_feedback"] = self._stats["intent_feedback"][-500:]

        self.logger.debug(
            "Intent feedback: detected=%s, actual=%s, correct=%s",
            detected_intent,
            actual_intent,
            detected_intent == actual_intent,
        )

    def get_intent_accuracy(self) -> dict:
        """
        Get intent detection accuracy metrics.

        Returns:
            Dictionary with accuracy stats
        """
        feedback = self._stats.get("intent_feedback", [])

        if not feedback:
            return {"accuracy": 0.0, "total_feedback": 0, "confusion_matrix": {}}

        correct = sum(1 for f in feedback if f.get("correct", False))
        total = len(feedback)

        # Build confusion matrix
        confusion = defaultdict(lambda: defaultdict(int))
        for f in feedback:
            confusion[f["detected"]][f["actual"]] += 1

        # Convert to regular dict
        confusion_dict = {k: dict(v) for k, v in confusion.items()}

        return {
            "accuracy": round(correct / total, 3) if total > 0 else 0.0,
            "correct": correct,
            "total_feedback": total,
            "confusion_matrix": confusion_dict,
        }

    def get_detailed_stats(self) -> dict:
        """
        Get comprehensive statistics including latency percentiles.

        Returns:
            Detailed statistics dictionary
        """
        summary = self.get_summary()
        latency = self.get_latency_percentiles()
        quality = self.get_quality_summary()
        intent = self.get_intent_accuracy()

        return {
            "summary": {
                "total_interactions": summary.total_interactions,
                "avg_response_time_ms": summary.avg_response_time_ms,
                "cache_hit_rate": summary.cache_hit_rate,
                "error_rate": summary.error_rate,
                "interactions_per_hour": summary.interactions_per_hour,
            },
            "latency_percentiles": latency,
            "quality": quality,
            "intent_accuracy": intent,
            "tokens": {
                "input": summary.total_input_tokens,
                "output": summary.total_output_tokens,
                "total": summary.total_input_tokens + summary.total_output_tokens,
            },
        }


# Global instance
ai_analytics = AIAnalytics()


async def log_ai_interaction(**kwargs) -> None:
    """Convenience function to log an interaction."""
    # Also record response time for percentiles
    if "response_time_ms" in kwargs:
        ai_analytics._record_response_time(kwargs["response_time_ms"])
    await ai_analytics.log_interaction(**kwargs)


def get_ai_stats() -> dict[str, Any]:
    """Get real-time AI statistics."""
    return ai_analytics.get_realtime_stats()


def get_detailed_ai_stats() -> dict[str, Any]:
    """Get detailed AI statistics including percentiles."""
    return ai_analytics.get_detailed_stats()
