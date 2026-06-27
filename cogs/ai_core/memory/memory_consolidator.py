"""
Conversation Summary Archiver.

Archives long-running conversation history into compact summary rows in
the ``conversation_summaries`` table, with optional opt-in deletion of the
originals (``CONSOLIDATOR_DELETE_ORIGINALS=1``). The summary itself is
extractive (key-sentence + topic-keyword) rather than LLM-generated; for
abstractive summaries see :mod:`cogs.ai_core.memory.summarizer`.

This module is **distinct** from :mod:`cogs.ai_core.memory.consolidator`:

  * ``consolidator.py`` extracts structured *facts* about characters from
    recent turns and feeds them into ``entity_memory`` to fight
    hallucinations. It is fact-oriented and runs every N messages.
  * ``memory_consolidator.py`` (this file) trims the *raw history* itself,
    rolling old turns into a one-line summary so the chat history table
    doesn't grow unboundedly. It is storage-oriented and runs every few
    hours.

Both files used to expose ``MemoryConsolidator``/``memory_consolidator``
as legacy aliases — those have been removed in favour of the explicit
:class:`SummaryArchiver` / :data:`summary_archiver` names so callers can
no longer accidentally grab the wrong subsystem.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# Try to import database
try:
    from utils.database import db

    DB_AVAILABLE = True
except ImportError:
    db = None  # type: ignore
    DB_AVAILABLE = False


logger = logging.getLogger(__name__)


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


class SummaryArchiver:
    """
    Archives old conversation history into compact summary rows.

    Features:
    - Summarizes old conversations to save context space
    - Preserves key topics and decisions
    - Periodic background consolidation
    - Tiered memory (recent > summary > archived)

    For abstractive (LLM-generated) summaries, see :class:`ConversationSummarizer`
    in :mod:`.summarizer` — this class only does extractive summarization
    (first/last user line + keyword topics) so it can run without an API key.
    """

    # Configuration
    MIN_MESSAGES_TO_SUMMARIZE = 20  # Minimum messages before summarizing
    SUMMARY_AGE_THRESHOLD_HOURS = 24  # Summarize messages older than this
    MAX_SUMMARY_LENGTH = 500
    # Upper bound on rows pulled into a single consolidation pass. Without it,
    # a very active channel with a large unsummarised backlog (consolidation
    # disabled for a while, or force=True) loads the entire backlog into memory
    # and does the join + topic extraction synchronously on the event loop in
    # one shot. Capping per-pass lets the backlog drain across successive runs
    # (oldest first, since the SELECT orders by timestamp ASC).
    MAX_MESSAGES_PER_CONSOLIDATION = 500

    def __init__(self):
        self.logger = logging.getLogger("SummaryArchiver")
        self._consolidation_task: asyncio.Task | None = None
        # Per-channel locks: the 6h background loop and the manual
        # !consolidate command can hit the same channel concurrently — both
        # would SELECT the same unsummarized rows and INSERT duplicate
        # summary rows (the summarized_at filter only prevents double-
        # MARKING, not double-summarizing).
        self._channel_locks: dict[int, asyncio.Lock] = {}
        # init_schema is idempotent DDL (CREATE … IF NOT EXISTS) but is called
        # lazily on every consolidate/query path; consolidate_all_channels can
        # invoke it ~20×/channel/cycle, each re-acquiring the global writer
        # lock for a no-op. Gate it behind a one-shot flag so the DDL+commit
        # runs once per process and later calls early-return.
        self._schema_ready = False

    def _get_channel_lock(self, channel_id: int) -> asyncio.Lock:
        lock = self._channel_locks.get(channel_id)
        if lock is not None:
            return lock
        # Bound growth: this dict otherwise keeps one Lock per distinct channel
        # forever (a slow leak on a long-running bot). When it grows large,
        # drop locks that aren't currently held — they're idle and a fresh one
        # is created on demand. A held lock is in active use, so it's kept.
        # Also keep locks with queued waiters: Lock.release() clears _locked
        # before the next waiter resumes, so during that handoff window
        # locked() is False while a coroutine is still about to acquire it —
        # evicting it there would orphan the lock and lose mutual exclusion.
        # Mirrors LongTermMemory._get_user_lock.
        if len(self._channel_locks) >= 10_000:
            for cid in [
                c
                for c, lk in self._channel_locks.items()
                if not lk.locked() and not getattr(lk, "_waiters", None)
            ]:
                del self._channel_locks[cid]
        return self._channel_locks.setdefault(channel_id, asyncio.Lock())

    async def init_schema(self) -> None:
        """Initialize database schema for summaries."""
        if not DB_AVAILABLE or db is None:
            return

        # Idempotent: the schema only needs creating once per process. Skip the
        # writer-lock acquisition + commit on every subsequent lazy call.
        if self._schema_ready:
            return

        # DDL must route through the single-writer connection and commit
        # explicitly — mirrors ``long_term_memory.init_schema``. Using the read
        # pool without a commit can leave the CREATE uncommitted (and risks a
        # "database is locked" error under WAL on Windows), so the table would
        # silently fail to persist on a fresh DB.
        async with db.get_write_connection() as conn:
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
            await conn.commit()

        self._schema_ready = True
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
        consecutive_errors = 0
        while True:
            try:
                await asyncio.sleep(interval_hours * 3600)
                await self.consolidate_all_channels()
                consecutive_errors = 0
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                # Cap exponent to prevent astronomical intermediate values.
                # 6 still gives a 64× factor (more than enough headroom
                # under any sane ``interval_hours``) while keeping the
                # intermediate exponent well below int-overflow / overflow
                # warning territory. 10 was theatre.
                capped_errors = min(consecutive_errors, 6)
                backoff = min(interval_hours * 3600, 60 * (2**capped_errors))
                self.logger.error(
                    "Consolidation error (attempt %d, backoff %.0fs): %s",
                    consecutive_errors,
                    backoff,
                    e,
                )
                await asyncio.sleep(backoff)

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

        # Serialize the whole select→summarize→save→mark sequence per
        # channel — see _channel_locks in __init__ for the duplicate-summary
        # race this prevents.
        async with self._get_channel_lock(channel_id):
            return await self._consolidate_channel_locked(channel_id, force)

    async def _consolidate_channel_locked(
        self, channel_id: int, force: bool = False
    ) -> ConversationSummary | None:
        """Body of consolidate_channel — caller holds the per-channel lock."""
        # Ensure the conversation_summaries table exists. SummaryArchiver.init_schema()
        # is not wired into bot startup, so a manual !consolidate on a fresh DB
        # would otherwise hit "no such table". init_schema is idempotent
        # (CREATE TABLE IF NOT EXISTS), so this lazy call is safe and cheap.
        await self.init_schema()

        # Get old messages to consolidate
        cutoff_time = datetime.now(tz=timezone.utc) - timedelta(
            hours=self.SUMMARY_AGE_THRESHOLD_HOURS
        )

        async with db.get_connection() as conn:
            # ISO-8601 strings sort lexically, so a plain string compare
            # uses the timestamp index. Wrapping ``timestamp`` in
            # ``datetime()`` would force a full table scan — its sibling
            # ``consolidate_all_channels`` already calls this out.
            #
            # ``summarized_at IS NULL`` (migration 015): skip rows already
            # rolled into a prior summary so we never produce duplicate
            # summary rows on re-run. The partial index
            # ``idx_ai_history_pending_summary`` only contains unsummarised
            # rows so this filter doesn't cost a scan.
            cursor = await conn.execute(
                # LIMIT caps a single pass so an unbounded backlog can't be
                # pulled into one synchronous summarization — see
                # MAX_MESSAGES_PER_CONSOLIDATION. Oldest rows go first
                # (ORDER BY timestamp ASC), so the backlog drains across runs.
                """
                SELECT id, role, content, timestamp
                FROM ai_history
                WHERE channel_id = ?
                  AND timestamp < ?
                  AND summarized_at IS NULL
                ORDER BY timestamp ASC, id ASC
                LIMIT ?
            """,
                (channel_id, cutoff_time.isoformat(), self.MAX_MESSAGES_PER_CONSOLIDATION),
            )
            rows = list(await cursor.fetchall())

        if len(rows) < self.MIN_MESSAGES_TO_SUMMARIZE and not force:
            return None

        # Generate summary
        messages = [{"role": row["role"], "content": row["content"]} for row in rows]

        summary = await self._generate_summary(messages)

        if not summary:
            return None

        # Store summary — guard malformed timestamps so a single bad row doesn't kill summarization
        def _parse_ts(value: Any) -> datetime | None:
            if value is None:
                return None
            try:
                return datetime.fromisoformat(str(value))
            except (TypeError, ValueError):
                logger.warning("Skipping malformed timestamp during summary: %r", value)
                return None

        start_time = _parse_ts(rows[0]["timestamp"]) if rows else None
        end_time = _parse_ts(rows[-1]["timestamp"]) if rows else None

        result = ConversationSummary(
            channel_id=channel_id,
            summary=summary["text"],
            key_topics=summary.get("topics", []),
            key_decisions=summary.get("decisions", []),
            start_time=start_time,
            end_time=end_time,
            message_count=len(rows),
            created_at=datetime.now(tz=timezone.utc),
        )

        # Save to database
        summary_id = await self._save_summary(result)

        # After the summary commits we MUST exclude these rows from the
        # next consolidation pass, otherwise a re-run would re-summarise
        # them and produce a duplicate. Two strategies:
        #
        # 1. Default — MARK the rows by stamping ``summarized_at`` (lossless
        #    and idempotent: re-running ``consolidate_channel`` is now a
        #    no-op for already-marked rows even if the very next mark fails
        #    halfway through).
        # 2. ``CONSOLIDATOR_DELETE_ORIGINALS=1`` — hard-delete after the
        #    mark, freeing storage. Mark-then-delete is safer than
        #    delete-only: a crash between mark and delete leaves rows that
        #    are correctly excluded from future passes (no duplicate
        #    summary), they just stay on disk until the next opt-in run.
        delete_originals = os.getenv("CONSOLIDATOR_DELETE_ORIGINALS", "0").lower() in (
            "1",
            "true",
            "yes",
        )
        if summary_id is not None:
            message_ids = [row["id"] for row in rows]
            try:
                await self._mark_consolidated_messages(message_ids)
            except Exception:
                self.logger.error(
                    "❌ Summary %d saved but mark-summarized of %d rows failed for "
                    "channel %d — returning None so the per-channel pass loop stops "
                    "instead of re-summarising the same unmarked rows. "
                    "Investigate DB write path.",
                    summary_id,
                    len(message_ids),
                    channel_id,
                    exc_info=True,
                )
                # The source rows still have summarized_at IS NULL, so the next
                # pass would re-pull and re-summarise them, INSERTing duplicate
                # conversation_summaries rows (no UNIQUE constraint). Signal "no
                # progress" so consolidate_all_channels breaks this channel's loop.
                return None
            else:
                if delete_originals:
                    try:
                        await self._delete_consolidated_messages(message_ids)
                    except Exception:
                        # Mark already succeeded so the rows won't be
                        # re-summarised; the only consequence here is that
                        # storage isn't reclaimed yet. Logged but not fatal.
                        self.logger.error(
                            "❌ Summary %d / mark OK but hard-delete of %d "
                            "originals failed for channel %d — rows remain "
                            "on disk; safe to retry.",
                            summary_id,
                            len(message_ids),
                            channel_id,
                            exc_info=True,
                        )
                else:
                    self.logger.debug(
                        "Summary saved for channel %d; originals marked summarized "
                        "(set CONSOLIDATOR_DELETE_ORIGINALS=1 to also hard-delete)",
                        channel_id,
                    )
            # Only report success when the summary was actually persisted. This
            # INFO previously ran unconditionally after the if/else, so a failed
            # save still logged "Consolidated …", masking the failure.
            self.logger.info("📦 Consolidated %d messages for channel %d", len(rows), channel_id)
        else:
            self.logger.warning(
                "⚠️ Summary save failed for channel %d — keeping original messages",
                channel_id,
            )
            # A failed save must not look like success: callers count a
            # non-None result as "consolidated" (consolidate_all_channels)
            # and !consolidate shows "สำเร็จ" — while nothing was persisted
            # and the source rows remain unmarked (re-summarized next pass).
            return None

        return result

    async def consolidate_all_channels(self) -> int:
        """Consolidate all channels that need it."""
        if not DB_AVAILABLE or db is None:
            return 0

        # Get channels with old messages
        cutoff = datetime.now(tz=timezone.utc) - timedelta(hours=self.SUMMARY_AGE_THRESHOLD_HOURS)

        async with db.get_connection() as conn:
            # Compare timestamps as raw strings (ISO-8601 sorts lexically)
            # so SQLite can use the timestamp index directly. Wrapping the
            # column in datetime() forced a full-table scan even when the
            # column was indexed.
            cursor = await conn.execute(
                """
                SELECT channel_id, COUNT(*) as count
                FROM ai_history
                WHERE timestamp < ? AND summarized_at IS NULL
                GROUP BY channel_id
                HAVING count >= ?
            """,
                (cutoff.isoformat(), self.MIN_MESSAGES_TO_SUMMARIZE),
            )
            channels = list(await cursor.fetchall())

        consolidated = 0
        # Drain each channel across multiple capped passes within THIS cycle
        # instead of one MAX_MESSAGES_PER_CONSOLIDATION (500-row) chunk per 6h
        # run — a large backlog used to take weeks to clear while ai_history kept
        # growing. consolidate_channel returns None once a channel has fewer than
        # MIN_MESSAGES_TO_SUMMARIZE eligible rows left (drained). Bounded by a
        # per-channel pass budget so one huge channel can't monopolise the cycle,
        # and yields to the event loop between passes.
        max_passes_per_channel = 20
        for row in channels:
            channel_id = row["channel_id"]
            for _ in range(max_passes_per_channel):
                result = await self.consolidate_channel(channel_id)
                if not result:
                    break
                consolidated += 1
                await asyncio.sleep(0)

        return consolidated

    async def get_channel_summaries(
        self, channel_id: int, limit: int = 5
    ) -> list[ConversationSummary]:
        """Get recent summaries for a channel."""
        if not DB_AVAILABLE or db is None:
            return []

        # Lazily ensure the table exists (see consolidate_channel) so a query
        # issued before any consolidation has run doesn't hit "no such table".
        await self.init_schema()

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

        def _safe_dt(val: Any) -> datetime | None:
            # Defensive parse: a malformed timestamp in DB shouldn't take
            # down the whole get_channel_summaries call. Mirror the
            # _parse_ts pattern used elsewhere in this module.
            if not val:
                return None
            try:
                return datetime.fromisoformat(val)
            except (TypeError, ValueError):
                return None

        summaries = []
        for row in rows:
            summary = ConversationSummary(
                id=row["id"],
                channel_id=row["channel_id"],
                summary=row["summary"],
                key_topics=self._load_json_list(row["key_topics"]),
                key_decisions=self._load_json_list(row["key_decisions"]),
                start_time=_safe_dt(row["start_time"]),
                end_time=_safe_dt(row["end_time"]),
                message_count=row["message_count"],
                created_at=_safe_dt(row["created_at"]),
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

        # Simple extractive approach:
        # Take first sentence from user, key points
        user_messages = [m["content"] for m in messages if m["role"] == "user" and m["content"]]

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

        # Topics reflect the *user's* subject matter, not AI verbiage: on a
        # Thai-first roleplay bot the assistant replies are far longer than the
        # user prompts, so joining both roles let high-frequency assistant prose
        # dominate the keyword counts. Restrict the topic source to user turns.
        # Cap the joined text before tokenizing: _extract_topics runs pythainlp
        # word_tokenize, which for up to MAX_MESSAGES_PER_CONSOLIDATION (500)
        # long turns would otherwise segment hundreds of KB of Thai in one shot.
        # Offload that synchronous segmentation to a thread so it can't block the
        # event loop (incl. the Discord heartbeat) while we hold the channel lock.
        topic_source = " ".join(user_messages)[:20000]
        topics = await asyncio.to_thread(self._extract_topics, topic_source)

        summary_text = " | ".join(key_sentences)
        if len(summary_text) > self.MAX_SUMMARY_LENGTH:
            summary_text = summary_text[: self.MAX_SUMMARY_LENGTH] + "..."

        # No user-role content → key_sentences is empty and summary_text is "".
        # Return None so consolidate_channel's `if not summary` guard bails
        # instead of marking/deleting the originals behind a content-free summary.
        if not summary_text.strip():
            return None

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

        # Tokenize. Latin words split cleanly on ``\b``, but Thai has no
        # inter-word spaces, so ``\b\w{4,}\b`` collapses a spaceless Thai run
        # into one mega-token AND the 4-char floor discards every (2-3 char)
        # Thai stopword in ``common_words`` above — making Thai key_topics
        # garbage on this Thai-first bot. Use pythainlp's segmenter when it's
        # installed (then the ``common_words`` filter actually applies to Thai);
        # otherwise fall back to the original Latin-script-oriented regex
        # unchanged, so behaviour is identical when pythainlp is absent.
        try:
            from pythainlp.tokenize import word_tokenize as _thai_word_tokenize

            words = [
                w.strip().lower()
                for w in _thai_word_tokenize(text)
                if len(w.strip()) >= 2 and not w.isspace()
            ]
        except Exception:
            # Extract words longer than 3 chars (Latin-script fallback)
            words = re.findall(r"\b\w{4,}\b", text.lower())

        # Count frequency
        word_counts: dict[str, int] = {}
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

        async with db.get_write_connection() as conn:
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
                    json.dumps(summary.key_topics, ensure_ascii=False)
                    if summary.key_topics
                    else "[]",
                    json.dumps(summary.key_decisions, ensure_ascii=False)
                    if summary.key_decisions
                    else "[]",
                    summary.start_time.isoformat() if summary.start_time else None,
                    summary.end_time.isoformat() if summary.end_time else None,
                    summary.message_count,
                ),
            )
            await conn.commit()
            return cursor.lastrowid  # type: ignore[no-any-return]

    async def _delete_consolidated_messages(self, message_ids: list[int]) -> None:
        """Delete messages that have been consolidated."""
        if not DB_AVAILABLE or db is None or not message_ids:
            return

        # Batch into chunks of 900 to avoid SQLite variable limit (default 999).
        # Wrap the whole thing in a single transaction so a partial failure
        # rolls back instead of leaving the table half-deleted while the
        # corresponding summary row is already committed.
        batch_size = 900
        async with db.get_write_connection() as conn:
            try:
                for i in range(0, len(message_ids), batch_size):
                    batch = message_ids[i : i + batch_size]
                    placeholders = ",".join("?" * len(batch))
                    await conn.execute(
                        f"DELETE FROM ai_history WHERE id IN ({placeholders})",  # nosec B608  # placeholders is '?,?,...'; values via batch
                        batch,
                    )
                await conn.commit()
            except Exception:
                with contextlib.suppress(Exception):
                    await conn.rollback()
                raise

    async def _mark_consolidated_messages(self, message_ids: list[int]) -> None:
        """Stamp ``summarized_at`` on rows we just rolled into a summary.

        Default replacement for the previous "hard-delete after save" flow.
        Re-applies idempotently: rows already marked stay at their first
        stamp (the ``WHERE summarized_at IS NULL`` filter ensures we never
        clobber a historical mark with a later one). Wrapping the whole
        batch in one transaction keeps mark-then-future-delete cleanly
        recoverable — if mark commits and the optional hard-delete then
        fails, the rows are out of the consolidation queue regardless.
        """
        if not DB_AVAILABLE or db is None or not message_ids:
            return

        marked_at = datetime.now(tz=timezone.utc).isoformat()
        batch_size = 900
        async with db.get_write_connection() as conn:
            try:
                for i in range(0, len(message_ids), batch_size):
                    batch = message_ids[i : i + batch_size]
                    placeholders = ",".join("?" * len(batch))
                    await conn.execute(
                        # ``IS NULL`` so a row that was somehow marked
                        # between our SELECT and now keeps its earlier
                        # stamp instead of getting overwritten.
                        f"UPDATE ai_history SET summarized_at = ? "  # nosec B608 - placeholders is '?,?,...'; values via params
                        f"WHERE summarized_at IS NULL AND id IN ({placeholders})",
                        [marked_at, *batch],
                    )
                await conn.commit()
            except Exception:
                with contextlib.suppress(Exception):
                    await conn.rollback()
                raise


# Global instance
summary_archiver = SummaryArchiver()
