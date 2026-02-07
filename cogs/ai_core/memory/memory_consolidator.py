"""
Memory Consolidation Module.
Summarizes long conversations into compact memory chunks.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

# Try to import database
try:
    from utils.database import db

    DB_AVAILABLE = True
except ImportError:
    db = None  # type: ignore
    DB_AVAILABLE = False


@dataclass
class ConversationSummary:
    """A summarized chunk of conversation."""

    id: int | None = None
    channel_id: int = 0
    user_id: int | None = None

    # Summary content
    summary: str = ""
    key_topics: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)

    # Time range covered
    start_time: datetime | None = None
    end_time: datetime | None = None
    message_count: int = 0

    # Metadata
    created_at: datetime | None = None

    def to_context_string(self) -> str:
        """Format for context injection."""
        parts = [
            f"[สรุปการสนทนา: {self.start_time.strftime('%d/%m/%Y') if self.start_time else 'N/A'}]"
        ]
        parts.append(self.summary)

        if self.key_topics:
            parts.append(f"หัวข้อ: {', '.join(self.key_topics[:3])}")

        return "\n".join(parts)


class ConversationSummarizer:
    """
    Consolidates conversation history into summaries.

    Features:
    - Summarizes old conversations to save context space
    - Preserves key topics and decisions
    - Periodic background consolidation
    - Tiered memory (recent > summary > archived)
    """

    # Configuration
    MIN_MESSAGES_TO_SUMMARIZE = 20  # Minimum messages before summarizing
    SUMMARY_AGE_THRESHOLD_HOURS = 24  # Summarize messages older than this
    MAX_SUMMARY_LENGTH = 500

    def __init__(self):
        self.logger = logging.getLogger("ConversationSummarizer")
        self._consolidation_task: asyncio.Task | None = None

    async def init_schema(self) -> None:
        """Initialize database schema for summaries."""
        if not DB_AVAILABLE or db is None:
            return

        async with db.get_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_summaries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id INTEGER NOT NULL,
                    user_id INTEGER,
                    summary TEXT NOT NULL,
                    key_topics TEXT,
                    key_decisions TEXT,
                    start_time DATETIME,
                    end_time DATETIME,
                    message_count INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_summaries_channel
                ON conversation_summaries(channel_id)
            """)

        self.logger.info("📚 Memory consolidator schema initialized")

    def start_background_task(self, interval_hours: float = 6.0) -> None:
        """Start periodic consolidation task."""
        if self._consolidation_task and not self._consolidation_task.done():
            return

        self._consolidation_task = asyncio.create_task(self._consolidation_loop(interval_hours))
        self.logger.info("🔄 Consolidation background task started")

    async def stop_background_task(self) -> None:
        """Stop the consolidation task."""
        if self._consolidation_task:
            self._consolidation_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consolidation_task
            self._consolidation_task = None

    async def _consolidation_loop(self, interval_hours: float) -> None:
        """Background consolidation loop."""
        while True:
            try:
                await asyncio.sleep(interval_hours * 3600)
                await self.consolidate_all_channels()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Consolidation error: %s", e)

    async def consolidate_channel(
        self, channel_id: int, force: bool = False
    ) -> ConversationSummary | None:
        """
        Consolidate old messages in a channel into a summary.

        Args:
            channel_id: Discord channel ID
            force: Force consolidation even if threshold not met

        Returns:
            Created summary or None
        """
        if not DB_AVAILABLE or db is None:
            return None

        # Get old messages to consolidate
        cutoff_time = datetime.now() - timedelta(hours=self.SUMMARY_AGE_THRESHOLD_HOURS)

        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT id, role, content, timestamp
                FROM ai_history
                WHERE channel_id = ? AND timestamp < ?
                ORDER BY timestamp ASC
            """,
                (channel_id, cutoff_time.isoformat()),
            )
            rows = list(await cursor.fetchall())

        if len(rows) < self.MIN_MESSAGES_TO_SUMMARIZE and not force:
            return None

        # Generate summary
        messages = [{"role": row["role"], "content": row["content"]} for row in rows]

        summary = await self._generate_summary(messages)

        if not summary:
            return None

        # Store summary
        start_time = datetime.fromisoformat(rows[0]["timestamp"]) if rows else None
        end_time = datetime.fromisoformat(rows[-1]["timestamp"]) if rows else None

        result = ConversationSummary(
            channel_id=channel_id,
            summary=summary["text"],
            key_topics=summary.get("topics", []),
            key_decisions=summary.get("decisions", []),
            start_time=start_time,
            end_time=end_time,
            message_count=len(rows),
            created_at=datetime.now(),
        )

        # Save to database
        await self._save_summary(result)

        # Delete consolidated messages (keep summary instead)
        message_ids = [row["id"] for row in rows]
        await self._delete_consolidated_messages(message_ids)

        self.logger.info("📦 Consolidated %d messages for channel %d", len(rows), channel_id)

        return result

    async def consolidate_all_channels(self) -> int:
        """Consolidate all channels that need it."""
        if not DB_AVAILABLE or db is None:
            return 0

        # Get channels with old messages
        cutoff = datetime.now() - timedelta(hours=self.SUMMARY_AGE_THRESHOLD_HOURS)

        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT channel_id, COUNT(*) as count
                FROM ai_history
                WHERE timestamp < ?
                GROUP BY channel_id
                HAVING count >= ?
            """,
                (cutoff.isoformat(), self.MIN_MESSAGES_TO_SUMMARIZE),
            )
            channels = list(await cursor.fetchall())

        consolidated = 0
        for row in channels:
            result = await self.consolidate_channel(row["channel_id"])
            if result:
                consolidated += 1

        return consolidated

    async def get_channel_summaries(
        self, channel_id: int, limit: int = 5
    ) -> list[ConversationSummary]:
        """Get recent summaries for a channel."""
        if not DB_AVAILABLE or db is None:
            return []

        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                SELECT * FROM conversation_summaries
                WHERE channel_id = ?
                ORDER BY end_time DESC
                LIMIT ?
            """,
                (channel_id, limit),
            )
            rows = list(await cursor.fetchall())

        summaries = []
        for row in rows:
            summary = ConversationSummary(
                id=row["id"],
                channel_id=row["channel_id"],
                summary=row["summary"],
                key_topics=self._load_json_list(row["key_topics"]),
                key_decisions=self._load_json_list(row["key_decisions"]),
                start_time=datetime.fromisoformat(row["start_time"]) if row["start_time"] else None,
                end_time=datetime.fromisoformat(row["end_time"]) if row["end_time"] else None,
                message_count=row["message_count"],
                created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
            )
            summaries.append(summary)

        return summaries

    async def get_context_summaries(self, channel_id: int) -> str:
        """Get summaries formatted for context injection."""
        summaries = await self.get_channel_summaries(channel_id, limit=3)

        if not summaries:
            return ""

        parts = ["=== ประวัติการสนทนาก่อนหน้า ==="]
        for summary in summaries:
            parts.append(summary.to_context_string())
            parts.append("")

        return "\n".join(parts)

    async def _generate_summary(self, messages: list[dict]) -> dict[str, Any] | None:
        """
        Generate a summary from messages.

        For now, uses extractive summarization (key sentences).
        Can be upgraded to use LLM for abstractive summaries.
        """
        if not messages:
            return None

        # Extract key information
        all_text = " ".join(m["content"] for m in messages if m["content"])

        # Simple extractive approach:
        # Take first sentence from user, key points
        user_messages = [m["content"] for m in messages if m["role"] == "user" and m["content"]]
        ai_messages = [m["content"] for m in messages if m["role"] == "model" and m["content"]]

        # Extract key sentences (simple heuristic)
        key_sentences = []

        # First user message (usually sets context)
        if user_messages:
            first_user = user_messages[0][:200]
            key_sentences.append(f"ผู้ใช้ถาม: {first_user}")

        # Last user message (most recent topic)
        if len(user_messages) > 1:
            last_user = user_messages[-1][:150]
            key_sentences.append(f"หัวข้อล่าสุด: {last_user}")

        # Extract topics using simple keyword extraction
        topics = self._extract_topics(all_text)

        summary_text = " | ".join(key_sentences)
        if len(summary_text) > self.MAX_SUMMARY_LENGTH:
            summary_text = summary_text[: self.MAX_SUMMARY_LENGTH] + "..."

        return {
            "text": summary_text,
            "topics": topics[:5],
            "decisions": [],  # Could be extracted with more sophisticated parsing
        }

    def _extract_topics(self, text: str) -> list[str]:
        """Extract key topics from text using simple heuristics."""
        import re

        # Remove common words
        common_words = {
            "the",
            "a",
            "an",
            "is",
            "are",
            "was",
            "were",
            "be",
            "been",
            "have",
            "has",
            "had",
            "do",
            "does",
            "did",
            "will",
            "would",
            "could",
            "should",
            "may",
            "might",
            "must",
            "shall",
            "ที่",
            "และ",
            "ของ",
            "ใน",
            "มี",
            "เป็น",
            "ได้",
            "ให้",
            "จะ",
            "ไม่",
            "ก็",
            "แต่",
            "หรือ",
            "ว่า",
            "กับ",
            "นี้",
            "นั้น",
        }

        # Extract words longer than 3 chars
        words = re.findall(r"\b\w{4,}\b", text.lower())

        # Count frequency
        word_counts = {}
        for word in words:
            if word not in common_words:
                word_counts[word] = word_counts.get(word, 0) + 1

        # Get top words
        sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
        return [word for word, count in sorted_words[:10] if count >= 2]

    @staticmethod
    def _load_json_list(value: str | None) -> list[str]:
        """Load a JSON list from a string, with fallback for comma-separated legacy data."""
        if not value:
            return []
        try:
            result = json.loads(value)
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            pass
        # Fallback: legacy comma-separated format
        return [item.strip() for item in value.split(",") if item.strip()]

    async def _save_summary(self, summary: ConversationSummary) -> int | None:
        """Save summary to database."""
        if not DB_AVAILABLE or db is None:
            return None

        async with db.get_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO conversation_summaries
                (channel_id, user_id, summary, key_topics, key_decisions,
                 start_time, end_time, message_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    summary.channel_id,
                    summary.user_id,
                    summary.summary,
                    json.dumps(summary.key_topics, ensure_ascii=False) if summary.key_topics else "[]",
                    json.dumps(summary.key_decisions, ensure_ascii=False) if summary.key_decisions else "[]",
                    summary.start_time.isoformat() if summary.start_time else None,
                    summary.end_time.isoformat() if summary.end_time else None,
                    summary.message_count,
                ),
            )
            return cursor.lastrowid

    async def _delete_consolidated_messages(self, message_ids: list[int]) -> None:
        """Delete messages that have been consolidated."""
        if not DB_AVAILABLE or db is None or not message_ids:
            return

        placeholders = ",".join("?" * len(message_ids))

        async with db.get_connection() as conn:
            await conn.execute(f"DELETE FROM ai_history WHERE id IN ({placeholders})", message_ids)


# Global instance
conversation_summarizer = ConversationSummarizer()

# Backward-compatible aliases
MemoryConsolidator = ConversationSummarizer
memory_consolidator = conversation_summarizer
