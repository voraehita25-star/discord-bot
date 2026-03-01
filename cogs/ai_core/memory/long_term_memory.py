"""
Long-term Memory Module.
Stores permanent facts about users that should never be forgotten.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any

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
                    data[key] = datetime.fromisoformat(data[key])
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
        # Confidence decays 10% per 30 days without confirmation
        decay_rate = 0.1
        decay_periods = days_since_confirmed / 30
        return max(0.1, 1.0 - (decay_rate * decay_periods))


class FactExtractor:
    """
    Extracts facts from messages using pattern matching.
    """

    # Patterns for extracting facts (pattern, category, importance)
    EXTRACTION_PATTERNS = [
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
        # Preference patterns
        (
            r"(?:ผม|ฉัน|ชั้น)(?:ชอบ|รัก|โปรด)\s*(.+?)(?:มาก|$)",
            FactCategory.PREFERENCE,
            ImportanceLevel.MEDIUM,
        ),
        (
            r"(?:ผม|ฉัน|ชั้น)(?:ไม่ชอบ|เกลียด)\s*(.+?)(?:มาก|$)",
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
        # Skill patterns
        (r"(?:ผม|ฉัน)(?:เป็น|เก่ง)(?:เรื่อง)?\s*(.+?)(?:$)", FactCategory.SKILL, ImportanceLevel.MEDIUM),
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
        now = datetime.now()

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

    def __init__(self):
        self.logger = logging.getLogger("LongTermMemory")
        self.extractor = FactExtractor()
        self._cache: dict[int, list[Fact]] = {}  # user_id -> facts
        self._next_cache_id: int = 0  # monotonic counter for cache-only IDs
        self._lock = asyncio.Lock()

    async def init_schema(self) -> None:
        """Initialize database schema for facts."""
        if not DB_AVAILABLE or db is None:
            return

        async with db.get_connection() as conn:
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

        stored_facts = []
        for fact in extracted:
            # Check for duplicates
            existing = await self._find_similar_fact(user_id, fact.content)

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
                    self.logger.info("Stored new fact: [%s] %s", fact.category, fact.content[:50])

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
            Stored fact or None if duplicate
        """
        # Check for duplicates
        existing = await self._find_similar_fact(user_id, content)
        if existing:
            await self._update_fact_confirmation(existing)
            return existing

        now = datetime.now()
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
            if DB_AVAILABLE and db is not None:
                async with db.get_write_connection() as conn:
                    await conn.execute(
                        "UPDATE user_facts SET is_active = 0 WHERE id = ?", (similar.id,)
                    )

            # Remove from cache
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
                return list(self._cache.get(user_id, []))

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

        facts = []
        for row in rows:
            fact = Fact(
                id=row["id"],
                user_id=row["user_id"],
                channel_id=row["channel_id"],
                category=row["category"],
                content=row["content"],
                importance=row["importance"],
                first_mentioned=datetime.fromisoformat(row["first_mentioned"])
                if row["first_mentioned"]
                else None,
                last_confirmed=datetime.fromisoformat(row["last_confirmed"])
                if row["last_confirmed"]
                else None,
                mention_count=row["mention_count"],
                confidence=row["confidence"],
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
        now = datetime.now()
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
        """Find existing similar fact."""
        facts = await self.get_user_facts(user_id)
        content_lower = content.lower()

        # Skip matching for very short content to avoid false positives
        if len(content_lower.strip()) < 5:
            return None

        for fact in facts:
            fact_lower = fact.content.lower()
            # Skip very short facts to avoid overly broad matches
            if len(fact_lower.strip()) < 5:
                continue
            # Simple substring matching
            if content_lower in fact_lower or fact_lower in content_lower:
                return fact
            # Word overlap
            content_words = set(content_lower.split())
            fact_words = set(fact_lower.split())
            if content_words and fact_words:
                overlap = len(content_words & fact_words) / max(len(content_words), len(fact_words))
                if overlap >= self.SIMILARITY_THRESHOLD:
                    return fact

        return None

    async def _store_fact(self, fact: Fact) -> int | None:
        """Store a fact to database."""
        if not DB_AVAILABLE or db is None:
            # Store in cache only (thread-safe)
            async with self._lock:
                if fact.user_id not in self._cache:
                    self._cache[fact.user_id] = []
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
            return cursor.lastrowid

    async def _update_fact_confirmation(self, fact: Fact) -> None:
        """Update fact's last confirmation time and count."""
        now = datetime.now()
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
        seen_contents = {}

        for fact in facts:
            content_key = fact.content.lower().strip()

            if content_key in seen_contents:
                # Mark duplicate as inactive
                if fact.id and DB_AVAILABLE and db is not None:
                    async with db.get_write_connection() as conn:
                        await conn.execute(
                            "UPDATE user_facts SET is_active = 0 WHERE id = ?", (fact.id,)
                        )
                removed += 1
            else:
                seen_contents[content_key] = fact.id

        if removed:
            self.logger.info("Removed %d duplicate facts for user %d", removed, user_id)

        return removed


# Global instance
long_term_memory = LongTermMemory()
