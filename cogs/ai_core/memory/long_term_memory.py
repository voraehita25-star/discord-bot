"""
Long-term Memory Module.
Stores permanent facts about users that should never be forgotten.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, ClassVar

# Try to import database
try:
    from utils.database import db

    DB_AVAILABLE = True
except ImportError:
    db = None  # type: ignore
    DB_AVAILABLE = False


class FactCategory(Enum):
    """Categories for facts."""

    IDENTITY = "identity"  # Name, nickname, etc.
    PREFERENCE = "preference"  # Likes, dislikes
    PERSONAL = "personal"  # Birthday, location, job
    RELATIONSHIP = "relationship"  # Family, friends
    SKILL = "skill"  # What they know
    CUSTOM = "custom"  # User-defined


class ImportanceLevel(Enum):
    """Importance levels for facts."""

    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4  # Never delete


@dataclass
class Fact:
    """
    Represents a permanent fact about a user.
    """

    id: int | None = None
    user_id: int = 0
    channel_id: int | None = None
    category: str = FactCategory.CUSTOM.value
    content: str = ""
    importance: int = ImportanceLevel.MEDIUM.value

    # Temporal tracking
    first_mentioned: datetime | None = None
    last_confirmed: datetime | None = None
    mention_count: int = 1
    confidence: float = 1.0

    # Source tracking
    source_message: str | None = None

    # Flags
    is_active: bool = True
    is_user_defined: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        data = asdict(self)
        for key in ["first_mentioned", "last_confirmed"]:
            if data[key]:
                data[key] = data[key].isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Fact:
        """Create from dictionary. Does not mutate the input dict."""
        # Work on a copy to avoid mutating the caller's dict
        data = dict(data)
        for key in ["first_mentioned", "last_confirmed"]:
            if data.get(key) and isinstance(data[key], str):
                try:
                    # Strip the trailing ``Z`` so legacy ISO timestamps
                    # written via ``isoformat() + "Z"`` parse cleanly on
                    # Python < 3.11 fromisoformat. Without this, those
                    # rows silently lose their datetime on rehydration.
                    data[key] = datetime.fromisoformat(data[key].replace("Z", "+00:00"))
                except ValueError:
                    data[key] = None
        # Filter to only known fields to avoid TypeError on unknown keys
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def decay_confidence(self, days_since_confirmed: int) -> float:
        """Calculate decayed confidence based on time since last confirmation.

        Returns the decayed confidence value without mutating self.
        """
        # Clamp negative days to 0 — a clock skew or "future" timestamp
        # would otherwise produce a confidence > 1.0 (i.e. negative decay).
        days = max(0, days_since_confirmed)
        # Confidence decays 10% per 30 days without confirmation
        decay_rate = 0.1
        decay_periods = days / 30
        return max(0.1, 1.0 - (decay_rate * decay_periods))


# Hard cap on the input length we run the extraction regex set against.
# Several patterns use unanchored ``(.+?)`` with alternation tails which
# is a ReDoS surface on adversarially long inputs; truncating bounds
# the worst-case backtracking cost without losing realistic content.
_MAX_FACT_EXTRACTION_LEN = 4096


class FactExtractor:
    """
    Extracts facts from messages using pattern matching.

    Note:
        This is the *offline* fact-extraction path — pure regex, runs on every
        user message, no API call. The patterns here are intentionally narrow
        (``IDENTITY`` + explicit "remember"/"forget" commands carry the most
        weight) so the noise rate stays low. When an Anthropic API key is
        configured, :mod:`cogs.ai_core.memory.consolidator` runs every N
        messages and extracts richer entity facts via Claude — that's the
        higher-quality path. Treat the FactExtractor output as a fast-but-
        rough first pass; the consolidator's results take precedence in
        ``entity_memory`` because they have higher confidence scores.
    """

    # Patterns for extracting facts (pattern, category, importance)
    EXTRACTION_PATTERNS: ClassVar[list[tuple[str, Any, Any]]] = [
        # Identity patterns
        (
            r"(?:ผม|ฉัน|ชั้น|เรา)(?:ชื่อ|นามว่า)\s*(.+?)(?:\s|$|ครับ|ค่ะ)",
            FactCategory.IDENTITY,
            ImportanceLevel.CRITICAL,
        ),
        (
            r"(?:my name is|i\'m called|call me)\s+(\w+)",
            FactCategory.IDENTITY,
            ImportanceLevel.CRITICAL,
        ),
        (
            r"(?:ชื่อ(?:ของ)?(?:ผม|ฉัน|เรา)(?:คือ|คือว่า)?)\s*(.+?)(?:\s|$)",
            FactCategory.IDENTITY,
            ImportanceLevel.CRITICAL,
        ),
        # Birthday/Age patterns
        (
            r"(?:วันเกิด(?:ของ)?(?:ผม|ฉัน|เรา)(?:คือ)?)\s*(.+?)(?:\s|$)",
            FactCategory.PERSONAL,
            ImportanceLevel.HIGH,
        ),
        (
            r"(?:my birthday is|born on)\s+(.+?)(?:\s|$)",
            FactCategory.PERSONAL,
            ImportanceLevel.HIGH,
        ),
        (r"(?:ผม|ฉัน)อายุ\s*(\d+)", FactCategory.PERSONAL, ImportanceLevel.MEDIUM),
        # Preference patterns. The lazy ``(.+?)`` followed by
        # ``(?:มาก|$)`` previously matched the smallest possible string
        # (often 1 char) — useless 2-char "facts" got captured then
        # filtered out at the length-cap check, wasting work. Anchor
        # on a sentence-end punctuation set OR ``มาก`` so we capture a
        # real preference noun phrase.
        (
            r"(?:ผม|ฉัน|ชั้น)(?:ชอบ|รัก|โปรด)\s+(.+?)(?:\s*มาก|[.!?\n]|$)",
            FactCategory.PREFERENCE,
            ImportanceLevel.MEDIUM,
        ),
        (
            r"(?:ผม|ฉัน|ชั้น)(?:ไม่ชอบ|เกลียด)\s+(.+?)(?:\s*มาก|[.!?\n]|$)",
            FactCategory.PREFERENCE,
            ImportanceLevel.MEDIUM,
        ),
        (
            r"(?:i (?:like|love|prefer))\s+(.+?)(?:\s|$|\.)",
            FactCategory.PREFERENCE,
            ImportanceLevel.MEDIUM,
        ),
        (
            r"(?:i (?:hate|dislike|don\'t like))\s+(.+?)(?:\s|$|\.)",
            FactCategory.PREFERENCE,
            ImportanceLevel.MEDIUM,
        ),
        # Work/Study patterns
        (
            r"(?:ผม|ฉัน)(?:ทำงาน|ทำอาชีพ|เป็น)\s*(.+?)(?:อยู่|$)",
            FactCategory.PERSONAL,
            ImportanceLevel.HIGH,
        ),
        (
            r"(?:i work as|i\'m a|my job is)\s+(.+?)(?:\s|$|\.)",
            FactCategory.PERSONAL,
            ImportanceLevel.HIGH,
        ),
        (r"(?:ผม|ฉัน)(?:เรียน|ศึกษา)\s*(.+?)(?:อยู่|$)", FactCategory.PERSONAL, ImportanceLevel.MEDIUM),
        # Skill patterns. ``(.+?)$`` was effectively ``(.+)`` once lazy
        # backtracking had to reach the end-of-string anchor — captured
        # the entire rest of the message as a "skill". Bound to a
        # sentence-terminating punctuation set so a normal sentence
        # produces a normal-sized capture.
        (
            r"(?:ผม|ฉัน)(?:เป็น|เก่ง)(?:เรื่อง)?\s+(.+?)(?:[.!?\n]|$)",
            FactCategory.SKILL,
            ImportanceLevel.MEDIUM,
        ),
        (
            r"(?:i know|i can|i\'m good at)\s+(.+?)(?:\s|$|\.)",
            FactCategory.SKILL,
            ImportanceLevel.MEDIUM,
        ),
        # Explicit remember commands
        (r"(?:จำไว้(?:ว่า)?|remember that)\s+(.+)", FactCategory.CUSTOM, ImportanceLevel.CRITICAL),
        (r"(?:อย่าลืม(?:ว่า)?|don\'t forget)\s+(.+)", FactCategory.CUSTOM, ImportanceLevel.CRITICAL),
    ]

    def __init__(self):
        self.logger = logging.getLogger("FactExtractor")
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), category, importance)
            for pattern, category, importance in self.EXTRACTION_PATTERNS
        ]

    def extract_facts(
        self, message: str, user_id: int, channel_id: int | None = None
    ) -> list[Fact]:
        """
        Extract facts from a message.

        Args:
            message: User message to analyze
            user_id: Discord user ID
            channel_id: Optional channel ID

        Returns:
            List of extracted facts
        """
        facts = []
        now = datetime.now(tz=timezone.utc)

        # Cap message length before regex evaluation. Several extraction
        # patterns use unanchored ``(.+?)`` with alternation tails — on
        # adversarially long input this is a ReDoS vector. 4096 bytes
        # is plenty for normal user messages and bounds the worst-case
        # backtracking cost. Truncate from the END so a "remember that
        # …" pattern at message tail still matches when present.
        if len(message) > _MAX_FACT_EXTRACTION_LEN:
            message = message[:_MAX_FACT_EXTRACTION_LEN]

        for pattern, category, importance in self._compiled_patterns:
            matches = pattern.findall(message)
            for match in matches:
                content = match.strip() if isinstance(match, str) else match[0].strip()

                if len(content) < 2 or len(content) > 200:
                    continue

                fact = Fact(
                    user_id=user_id,
                    channel_id=channel_id,
                    category=category.value,
                    content=content,
                    importance=importance.value,
                    first_mentioned=now,
                    last_confirmed=now,
                    mention_count=1,
                    source_message=message[:200],
                    is_user_defined=category == FactCategory.CUSTOM,
                )
                facts.append(fact)

                self.logger.debug(
                    "Extracted fact: [%s] %s (importance: %d)",
                    category.value,
                    content[:50],
                    importance.value,
                )

        return facts


class LongTermMemory:
    """
    Manages permanent facts storage with temporal tracking.

    Features:
    - Automatic fact extraction from messages
    - Explicit memory commands (!remember, !forget)
    - Confidence decay over time
    - Deduplication of similar facts
    - Category-based organization
    """

    SIMILARITY_THRESHOLD = 0.8
    MAX_CACHE_USERS = 500  # Maximum users to cache facts for

    def __init__(self):
        self.logger = logging.getLogger("LongTermMemory")
        self.extractor = FactExtractor()
        # OrderedDict + move_to_end gives true LRU eviction so heavily-used
        # users aren't kicked out just because they were inserted first.
        self._cache: OrderedDict[int, list[Fact]] = OrderedDict()
        self._next_cache_id: int = 0  # monotonic counter for cache-only IDs
        self._lock = asyncio.Lock()
        # Per-user lock guarding ``add_explicit_fact`` AND
        # ``process_message``. Separate from ``self._lock`` because the
        # storage helpers (``_store_fact`` / ``_update_fact_confirmation``)
        # already lock and asyncio.Lock is not reentrant. The schema has
        # no UNIQUE(user_id, content) constraint, so two concurrent
        # ``process_message`` calls for the same user could both miss the
        # similarity check and double-insert — this lock closes that
        # window without touching schema migrations.
        self._explicit_fact_locks: dict[int, asyncio.Lock] = {}

    def _get_user_lock(self, user_id: int) -> asyncio.Lock:
        """Return the per-user asyncio Lock, creating it on demand.

        Uses ``setdefault`` with a small sentinel-then-replace shape so
        the rare race where two coroutines hit a missing key simultaneously
        still ends up sharing one Lock — the loser's freshly-built Lock
        is discarded immediately.
        """
        lock = self._explicit_fact_locks.get(user_id)
        if lock is not None:
            return lock
        # Bound growth: this dict otherwise keeps one Lock per distinct user
        # forever (a slow leak on a long-running bot). When it grows large,
        # drop locks that aren't currently held — they're idle and a fresh one
        # is created on demand. A held lock is in active use, so it's kept.
        if len(self._explicit_fact_locks) >= 10_000:
            for uid in [u for u, lk in self._explicit_fact_locks.items() if not lk.locked()]:
                del self._explicit_fact_locks[uid]
        new_lock = asyncio.Lock()
        existing = self._explicit_fact_locks.setdefault(user_id, new_lock)
        return existing

    async def init_schema(self) -> None:
        """Initialize database schema for facts."""
        if not DB_AVAILABLE or db is None:
            return

        # DDL must route through the single-writer connection; otherwise two
        # cogs racing through ``init_schema`` against a fresh DB can both
        # see "table doesn't exist" and run CREATE TABLE concurrently.
        # SQLite serialises the actual CREATE but cross-connection DDL
        # under WAL has historically surfaced "database is locked" on
        # Windows. ``get_write_connection`` routes via the writer lock.
        async with db.get_write_connection() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    importance INTEGER DEFAULT 2,
                    first_mentioned DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_confirmed DATETIME DEFAULT CURRENT_TIMESTAMP,
                    mention_count INTEGER DEFAULT 1,
                    confidence REAL DEFAULT 1.0,
                    source_message TEXT,
                    is_active BOOLEAN DEFAULT 1,
                    is_user_defined BOOLEAN DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_facts_user
                ON user_facts(user_id, is_active)
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_facts_category
                ON user_facts(user_id, category)
            """)
            await conn.commit()

        self.logger.info("📚 Long-term memory schema initialized")

    async def process_message(
        self, message: str, user_id: int, channel_id: int | None = None
    ) -> list[Fact]:
        """
        Process a message for fact extraction and storage.

        Args:
            message: User message
            user_id: Discord user ID
            channel_id: Optional channel ID

        Returns:
            List of newly stored facts
        """
        # Extract facts from message
        extracted = self.extractor.extract_facts(message, user_id, channel_id)

        if not extracted:
            return []

        # Serialize concurrent ``process_message`` calls for the SAME user
        # so two near-simultaneous messages can't both miss the dedup
        # check and both insert. The schema has no UNIQUE constraint on
        # ``(user_id, content)``, so the lock is the only defence.
        async with self._get_user_lock(user_id):
            # Fetch the user's existing fact list ONCE — _find_similar_fact
            # used to re-fetch on every loop iteration, which is O(N²) on
            # the DB read for a single message that extracts N facts.
            existing_facts = await self.get_user_facts(user_id)

            stored_facts = []
            for fact in extracted:
                # Check for duplicates against the running list. Each newly stored
                # fact is appended to existing_facts (below), so later facts in the
                # same message ARE deduped against facts stored earlier in this
                # loop; the extractor additionally de-dupes its own output first.
                existing = self._find_similar_fact_in(existing_facts, fact.content)

                if existing:
                    # Update existing fact
                    await self._update_fact_confirmation(existing)
                    self.logger.debug("Updated existing fact: %s", existing.content[:30])
                else:
                    # Store new fact
                    fact_id = await self._store_fact(fact)
                    if fact_id:
                        fact.id = fact_id
                        stored_facts.append(fact)
                        existing_facts.append(fact)
                        self.logger.info(
                            "Stored new fact: [%s] %s", fact.category, fact.content[:50]
                        )

            return stored_facts

    async def add_explicit_fact(
        self,
        user_id: int,
        content: str,
        channel_id: int | None = None,
        category: str = FactCategory.CUSTOM.value,
    ) -> Fact | None:
        """
        Add a fact explicitly requested by user.

        Args:
            user_id: Discord user ID
            content: Fact content
            channel_id: Optional channel ID
            category: Fact category

        Returns:
            The stored Fact on success, the EXISTING Fact when the content
            duplicates one already stored, or None only when the underlying
            store failed (``_store_fact`` returned no id). Callers must treat
            None as a failure — not as "duplicate".
        """
        # Serialize concurrent ``add_explicit_fact`` calls for the SAME
        # user so two near-simultaneous calls (e.g. user double-clicking
        # a "remember this" button) don't both see "no duplicate" and
        # both insert. Uses the same per-user lock as ``process_message``
        # so the two paths can't double-insert through each other either.
        async with self._get_user_lock(user_id):
            existing = await self._find_similar_fact(user_id, content)
            if existing:
                await self._update_fact_confirmation(existing)
                return existing

            now = datetime.now(tz=timezone.utc)
            fact = Fact(
                user_id=user_id,
                channel_id=channel_id,
                category=category,
                content=content,
                importance=ImportanceLevel.CRITICAL.value,
                first_mentioned=now,
                last_confirmed=now,
                is_user_defined=True,
            )

            fact_id = await self._store_fact(fact)
            if fact_id:
                fact.id = fact_id
                return fact

        return None

    async def forget_fact(self, user_id: int, content_query: str) -> bool:
        """
        Mark a fact as inactive (forget it).

        Args:
            user_id: Discord user ID
            content_query: Search query for fact to forget

        Returns:
            True if fact was found and forgotten
        """
        similar = await self._find_similar_fact(user_id, content_query)
        if similar and similar.id:
            # Hold _lock across BOTH the DB write and the cache mutation.
            # `_update_fact_confirmation` holds the same lock across its DB
            # write, so doing only the cache update under lock here would
            # let an interleaving cache rebuild from the DB observe the
            # not-yet-deactivated row.
            async with self._lock:
                if DB_AVAILABLE and db is not None:
                    async with db.get_write_connection() as conn:
                        await conn.execute(
                            "UPDATE user_facts SET is_active = 0 WHERE id = ?", (similar.id,)
                        )
                        await conn.commit()

                if user_id in self._cache:
                    self._cache[user_id] = [f for f in self._cache[user_id] if f.id != similar.id]

            self.logger.info("Forgot fact: %s", similar.content[:50])
            return True

        return False

    async def get_user_facts(
        self, user_id: int, category: str | None = None, include_inactive: bool = False
    ) -> list[Fact]:
        """
        Get all facts for a user.

        Args:
            user_id: Discord user ID
            category: Optional filter by category
            include_inactive: Include forgotten facts

        Returns:
            List of facts
        """
        if not DB_AVAILABLE or db is None:
            async with self._lock:
                # Warn near capacity — without DB, every miss past
                # MAX_CACHE_USERS evicts the LRU user's facts. Surface
                # this so operators know facts are being lost in
                # cache-only mode before it actually happens.
                # Only warn on a MISS for a new user (the only case a later store
                # could evict) — otherwise this fires on every cache HIT once near
                # capacity, flooding logs with no actual imminent loss.
                if user_id not in self._cache and len(self._cache) >= self.MAX_CACHE_USERS - 10:
                    self.logger.warning(
                        "LTM cache near capacity (%d/%d) with DB unavailable — "
                        "next new user will evict oldest user's facts",
                        len(self._cache),
                        self.MAX_CACHE_USERS,
                    )
                if user_id in self._cache:
                    self._cache.move_to_end(user_id)
                facts = list(self._cache.get(user_id, []))
            # Apply the same filters the DB branch honors below; without this the
            # cache-only path silently ignored category/include_inactive and
            # returned every fact regardless of the requested filter.
            if category:
                facts = [f for f in facts if f.category == category]
            if not include_inactive:
                facts = [f for f in facts if f.is_active]
            return facts

        async with db.get_connection() as conn:
            if category:
                query = """
                    SELECT * FROM user_facts
                    WHERE user_id = ? AND category = ?
                """
                params = [user_id, category]
            else:
                query = "SELECT * FROM user_facts WHERE user_id = ?"
                params = [user_id]

            if not include_inactive:
                query += " AND is_active = 1"

            query += " ORDER BY importance DESC, last_confirmed DESC"

            cursor = await conn.execute(query, params)
            rows = await cursor.fetchall()

        def _parse_ts(value: str | None) -> datetime | None:
            """Parse a stored timestamp, normalising to tz-aware UTC.

            ``isoformat()``-written rows already carry ``+00:00``; rows
            written via SQLite's ``DEFAULT CURRENT_TIMESTAMP`` come back
            naive. Mixed sets used to crash ``get_context_facts`` when it
            subtracted a naive value from a tz-aware ``now``.
            """
            if not value:
                return None
            try:
                parsed = datetime.fromisoformat(value)
            except (TypeError, ValueError):
                # A single malformed historic row would otherwise abort
                # the entire ``get_user_facts`` call. Drop the timestamp
                # for that row but keep the rest of the result set usable.
                return None
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed

        facts = []
        for row in rows:
            # ``source_message`` round-trip preservation. The cache-only
            # branch saves ``source_message`` (long_term_memory.py
            # ``process_message``) but the DB-backed path silently
            # dropped it on the way back, so a fact looked up after a
            # write would have ``source_message=None`` even though the
            # column was populated. Use ``row.keys()`` to gracefully
            # handle older DB schemas that pre-date the column.
            row_keys = row.keys() if hasattr(row, "keys") else ()
            source_message = row["source_message"] if "source_message" in row_keys else None
            fact = Fact(
                id=row["id"],
                user_id=row["user_id"],
                channel_id=row["channel_id"],
                category=row["category"],
                content=row["content"],
                importance=row["importance"],
                first_mentioned=_parse_ts(row["first_mentioned"]),
                last_confirmed=_parse_ts(row["last_confirmed"]),
                mention_count=row["mention_count"],
                confidence=row["confidence"],
                source_message=source_message,
                is_active=bool(row["is_active"]),
                is_user_defined=bool(row["is_user_defined"]),
            )
            facts.append(fact)

        return facts

    async def get_context_facts(self, user_id: int, limit: int = 10) -> str:
        """
        Get facts formatted for injection into context.

        Args:
            user_id: Discord user ID
            limit: Maximum facts to include

        Returns:
            Formatted string for context injection
        """
        facts = await self.get_user_facts(user_id)
        if not facts:
            return ""

        # Decay confidence for old facts (use local variable to avoid mutating cached objects)
        now = datetime.now(tz=timezone.utc)
        scored_facts = []
        for fact in facts:
            if fact.last_confirmed:
                days_old = (now - fact.last_confirmed).days
                decayed_confidence = fact.decay_confidence(days_old)
            else:
                decayed_confidence = fact.confidence
            scored_facts.append((fact, decayed_confidence))

        # Sort by importance and decayed confidence
        scored_facts.sort(key=lambda pair: (pair[0].importance, pair[1]), reverse=True)
        scored_facts = scored_facts[:limit]

        # Format for context
        lines = ["สิ่งที่รู้เกี่ยวกับผู้ใช้นี้:"]
        for fact, decayed_conf in scored_facts:
            confidence_marker = "✓" if decayed_conf > 0.7 else "?"
            lines.append(f"- {fact.content} {confidence_marker}")

        return "\n".join(lines)

    async def _find_similar_fact(self, user_id: int, content: str) -> Fact | None:
        """Find existing similar fact (fetches user facts then delegates)."""
        facts = await self.get_user_facts(user_id)
        return self._find_similar_fact_in(facts, content)

    def _find_similar_fact_in(self, facts: list[Fact], content: str) -> Fact | None:
        """Find a similar fact within an already-fetched fact list.

        Pre-computes the query word set + length once outside the loop —
        previously this was rebuilt per-fact, making the function O(N*M)
        where N is the user's fact count. Also requires a substring match
        to be at least half the longer string's length so "John" doesn't
        spuriously dedupe "John Smith died yesterday".
        """
        content_lower = content.lower().strip()
        if not content_lower or not facts:
            return None
        # Exact match works at ANY length — the <5 bail-out below previously
        # let short facts (2-4 char Thai nicknames like "บอม") bypass dedup
        # entirely, inserting a fresh identical row on every mention.
        for fact in facts:
            if fact.content.lower().strip() == content_lower:
                return fact
        if len(content_lower) < 5:
            # Too short for the fuzzy substring/Jaccard checks below.
            return None

        content_words = set(content_lower.split())
        content_len = len(content_lower)

        for fact in facts:
            fact_lower = fact.content.lower().strip()
            if len(fact_lower) < 5:
                continue
            # Substring match — require the shorter string to be at least
            # 50% of the longer one. Stops "name" prefix matches from
            # treating arbitrary longer facts as duplicates.
            min_len = min(content_len, len(fact_lower))
            max_len = max(content_len, len(fact_lower))
            if (
                max_len > 0
                and min_len * 2 >= max_len
                and (content_lower in fact_lower or fact_lower in content_lower)
            ):
                return fact
            # Word overlap (Jaccard-ish) — only meaningful when both
            # sides have multi-word content.
            if content_words:
                fact_words = set(fact_lower.split())
                if fact_words:
                    overlap = len(content_words & fact_words) / max(
                        len(content_words), len(fact_words)
                    )
                    if overlap >= self.SIMILARITY_THRESHOLD:
                        return fact

        return None

    async def _store_fact(self, fact: Fact) -> int | None:
        """Store a fact to database."""
        if not DB_AVAILABLE or db is None:
            # Store in cache only (thread-safe)
            async with self._lock:
                if fact.user_id not in self._cache:
                    # Evict least-recently-used user cache if at capacity
                    if len(self._cache) >= self.MAX_CACHE_USERS:
                        oldest_uid, _ = self._cache.popitem(last=False)
                        # Promoted from debug — eviction in cache-only mode
                        # silently destroys a user's facts, so operators
                        # need to see it.
                        self.logger.warning(
                            "Evicted LTM cache for user %s (capacity %d) — facts lost (DB unavailable)",
                            oldest_uid,
                            self.MAX_CACHE_USERS,
                        )
                    self._cache[fact.user_id] = []
                else:
                    self._cache.move_to_end(fact.user_id)
                self._next_cache_id += 1
                fact.id = self._next_cache_id
                self._cache[fact.user_id].append(fact)
                return fact.id

        async with db.get_write_connection() as conn:
            cursor = await conn.execute(
                """
                INSERT INTO user_facts
                (user_id, channel_id, category, content, importance,
                 first_mentioned, last_confirmed, mention_count, confidence,
                 source_message, is_active, is_user_defined)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    fact.user_id,
                    fact.channel_id,
                    fact.category,
                    fact.content,
                    fact.importance,
                    fact.first_mentioned.isoformat() if fact.first_mentioned else None,
                    fact.last_confirmed.isoformat() if fact.last_confirmed else None,
                    fact.mention_count,
                    fact.confidence,
                    fact.source_message,
                    fact.is_active,
                    fact.is_user_defined,
                ),
            )
            await conn.commit()
            return cursor.lastrowid  # type: ignore[no-any-return]

    async def _update_fact_confirmation(self, fact: Fact) -> None:
        """Update fact's last confirmation time and count."""
        now = datetime.now(tz=timezone.utc)
        # Hold the lock across the in-memory mutation so a concurrent
        # forget_fact() (which rewrites the cache list under the same
        # lock) can't read a torn fact mid-update. The DB UPDATE is also
        # inside the lock so the persisted state matches what the cache
        # ends up with.
        async with self._lock:
            fact.last_confirmed = now
            fact.mention_count += 1
            fact.confidence = 1.0  # Reset confidence on confirmation

            if DB_AVAILABLE and db is not None and fact.id:
                async with db.get_write_connection() as conn:
                    await conn.execute(
                        """
                        UPDATE user_facts
                        SET last_confirmed = ?, mention_count = mention_count + 1, confidence = 1.0
                        WHERE id = ?
                    """,
                        (now.isoformat(), fact.id),
                    )
                    await conn.commit()

    async def deduplicate_facts(self, user_id: int) -> int:
        """
        Remove duplicate facts for a user.

        Returns:
            Number of duplicates removed
        """
        facts = await self.get_user_facts(user_id)
        if len(facts) < 2:
            return 0

        removed = 0
        seen_contents: dict[str, int | None] = {}
        removed_ids: list[int] = []

        for fact in facts:
            content_key = fact.content.lower().strip()

            if content_key in seen_contents:
                if fact.id:
                    # Mark duplicate as inactive — explicit commit so the
                    # `is_active = 0` write is durable even if the db manager's
                    # context exit doesn't auto-commit.
                    if DB_AVAILABLE and db is not None:
                        async with db.get_write_connection() as conn:
                            await conn.execute(
                                "UPDATE user_facts SET is_active = 0 WHERE id = ?", (fact.id,)
                            )
                            await conn.commit()
                    removed_ids.append(fact.id)
                    removed += 1
            else:
                seen_contents[content_key] = fact.id

        # Prune the in-memory cache too, so get_user_facts stops returning the
        # duplicates. This is required in cache-only mode (DB unavailable), where
        # the is_active=0 write above never runs, and is harmless otherwise.
        # Mirrors forget_fact's lock-guarded cache mutation.
        if removed_ids:
            drop = set(removed_ids)
            async with self._lock:
                if user_id in self._cache:
                    self._cache[user_id] = [f for f in self._cache[user_id] if f.id not in drop]

        if removed:
            self.logger.info("Removed %d duplicate facts for user %d", removed, user_id)

        return removed


# Global instance
long_term_memory = LongTermMemory()
