"""
Entity Memory System
Stores and retrieves structured entity information (characters, locations, items).
Prevents AI from hallucinating facts by providing verified entity data.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

# Database manager
try:
    from utils.database import db as db_manager
except ImportError:
    db_manager = None  # type: ignore[assignment]


@dataclass
class EntityFacts:
    """Structured facts about an entity."""

    # Common fields
    description: str | None = None

    # Character-specific
    age: int | None = None
    occupation: str | None = None
    personality: str | None = None
    appearance: str | None = None
    relationships: dict[str, str] = field(default_factory=dict)  # {"Min Chae-won": "sister"}

    # Location-specific
    location_type: str | None = None  # apartment, cafe, university
    address: str | None = None

    # Item-specific
    owner: str | None = None
    item_type: str | None = None

    # Custom fields
    custom: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary, excluding None / empty container values."""
        result = {}
        for key, value in asdict(self).items():
            if value is None:
                continue
            # Skip empty containers — `value not in ({}, [])` was a buggy
            # tuple membership test (an empty dict isn't equal to an empty
            # set) so empty `relationships`/`custom` dicts always passed
            # through and bloated the AI payload.
            if isinstance(value, dict | list | set | tuple) and not value:
                continue
            result[key] = value
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EntityFacts:
        """Create EntityFacts from dictionary."""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        known_data = {k: v for k, v in data.items() if k in known_fields}
        custom_data = {k: v for k, v in data.items() if k not in known_fields}
        if custom_data:
            known_data["custom"] = {**known_data.get("custom", {}), **custom_data}
        return cls(**known_data)

    def to_prompt_text(self) -> str:
        """Convert to human-readable text for prompt injection."""

        # Cap each field so a single over-long extracted value (or one
        # injected via a poisoned conversation) can't blow up the prompt /
        # context budget. Mirrors the truncation discipline state_tracker
        # already applies to its analogous fields.
        def _cap(value: object, limit: int = 500) -> str:
            text = str(value)
            return text if len(text) <= limit else text[:limit] + "…"

        lines = []
        if self.description:
            lines.append(f"คำอธิบาย: {_cap(self.description)}")
        if self.age:
            lines.append(f"อายุ: {_cap(self.age, 32)} ปี")
        if self.occupation:
            lines.append(f"อาชีพ: {_cap(self.occupation, 120)}")
        if self.personality:
            lines.append(f"นิสัย: {_cap(self.personality)}")
        if self.appearance:
            lines.append(f"รูปลักษณ์: {_cap(self.appearance)}")
        if self.relationships:
            rel_str = ", ".join([f"{k}: {v}" for k, v in self.relationships.items()])
            lines.append(f"ความสัมพันธ์: {_cap(rel_str)}")
        if self.location_type:
            lines.append(f"ประเภทสถานที่: {_cap(self.location_type, 120)}")
        if self.address:
            lines.append(f"ที่อยู่: {_cap(self.address)}")
        if self.owner:
            lines.append(f"เจ้าของ: {_cap(self.owner, 120)}")
        if self.custom:
            # Bound the number of custom rows too — an attacker-influenced
            # extraction could otherwise pack hundreds of keys in here.
            for k, v in list(self.custom.items())[:20]:
                lines.append(f"{_cap(k, 64)}: {_cap(v, 300)}")
        return "\n".join(lines)


@dataclass
class Entity:
    """Represents an entity in memory."""

    entity_id: int
    name: str
    entity_type: str  # character, location, item, event
    facts: EntityFacts
    channel_id: int | None = None
    guild_id: int | None = None
    confidence: float = 1.0  # How confident we are about this entity
    source: str = "user"  # user, ai_extracted, manual
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0

    def to_prompt_text(self) -> str:
        """Convert to text for prompt injection.

        Strips control characters and bracket-prefixed lines that look like
        synthetic system markers (``[SYSTEM]``, ``[INST]``, ``ignore previous``)
        — entity facts are derived from user/AI conversation and could be
        used as a stored prompt-injection vector if echoed verbatim into
        the model's prompt.
        """
        import re as _re

        facts_text = self.facts.to_prompt_text()

        def _scrub(s: str) -> str:
            # Drop ASCII control chars except whitespace.
            s = "".join(ch for ch in s if ch >= " " or ch in ("\n", "\t"))
            # Neutralise leading bracketed system markers per line.
            s = _re.sub(
                r"(?im)^\s*\[\s*(?:system|inst|user|assistant|ignore[^\]]*)\s*\][^\n]*",
                "[redacted]",
                s,
            )
            return s

        # ``entity_type`` ALSO needs scrubbing — extracted-data flows can
        # set it to anything (``add_entity`` accepts ``entity_data.get("type",
        # "character")`` from arbitrary upstream JSON), and an attacker who
        # gets a string like ``CHARACTER]\n[SYSTEM] ignore prior`` past
        # validation could inject prompt-control framing. Apply the same
        # bracket-redact + control-char strip the name and facts get.
        return f"[{_scrub(self.entity_type).upper()}] {_scrub(self.name)}:\n{_scrub(facts_text)}"


class EntityMemoryManager:
    """Manages entity memory storage and retrieval."""

    # SQL for creating entity_memories table
    CREATE_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS entity_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        facts TEXT NOT NULL,
        channel_id INTEGER,
        guild_id INTEGER,
        confidence REAL DEFAULT 1.0,
        source TEXT DEFAULT 'user',
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        access_count INTEGER DEFAULT 0,
        UNIQUE(name, channel_id, guild_id)
    );
    """

    CREATE_INDEX_SQL = """
    CREATE INDEX IF NOT EXISTS idx_entity_name ON entity_memories(name);
    CREATE INDEX IF NOT EXISTS idx_entity_type ON entity_memories(entity_type);
    CREATE INDEX IF NOT EXISTS idx_entity_channel ON entity_memories(channel_id);
    CREATE INDEX IF NOT EXISTS idx_entity_guild ON entity_memories(guild_id);
    CREATE INDEX IF NOT EXISTS idx_entity_guild_channel ON entity_memories(guild_id, channel_id);
    CREATE INDEX IF NOT EXISTS idx_entity_updated_at ON entity_memories(updated_at DESC);
    """

    def __init__(self):
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the entity memory table."""
        if self._initialized or not db_manager:
            return self._initialized  # type: ignore[no-any-return]

        try:
            async with db_manager.get_connection() as conn:
                await conn.execute(self.CREATE_TABLE_SQL)
                for sql in self.CREATE_INDEX_SQL.strip().split(";"):
                    if sql.strip():
                        await conn.execute(sql)
                await conn.commit()
            self._initialized = True
            logger.info("🧠 Entity Memory table initialized")
            return True
        except aiosqlite.Error:
            logger.exception("Failed to initialize entity memory table")
            return False

    async def add_entity(
        self,
        name: str,
        entity_type: str,
        facts: EntityFacts,
        channel_id: int | None = None,
        guild_id: int | None = None,
        confidence: float = 1.0,
        source: str = "user",
    ) -> int | None:
        """Add a new entity to memory. Returns entity ID or None if failed."""
        if not await self.initialize():
            return None

        # Safety check: ensure db_manager is still available after initialize
        if db_manager is None:
            logger.error("Database manager became unavailable after initialization")
            return None

        try:
            now = time.time()
            facts_json = json.dumps(facts.to_dict(), ensure_ascii=False)

            async with db_manager.get_write_connection() as conn:
                # BEGIN IMMEDIATE acquires the SQLite reserved-lock up front
                # so the SELECT below can't see a phantom row inserted by a
                # second writer between our check and our INSERT. The outer
                # asyncio _write_lock already serializes writers, but this
                # also protects against any path that bypasses it.
                #
                # Skip the BEGIN when a transaction is already open — most
                # commonly because aiosqlite auto-began one on the prior
                # commit. The previous shape caught the OperationalError
                # by message-string substring match ("transaction within
                # a transaction"), which is fragile across aiosqlite
                # versions / locales. Use the explicit ``in_transaction``
                # property instead so a different OperationalError (db
                # locked, disk full, etc.) still propagates loudly.
                in_tx = getattr(conn, "in_transaction", False)
                if not in_tx:
                    await conn.execute("BEGIN IMMEDIATE")
                # Track whether WE began the transaction so rollback-on-error
                # only targets our own BEGIN. If we joined an existing tx the
                # outer caller owns the rollback decision.
                _own_tx = not in_tx
                # Explicit check for existing entity to handle NULL values
                # in UNIQUE constraint (SQLite treats NULLs as distinct)
                if channel_id is None and guild_id is None:
                    check_cursor = await conn.execute(
                        "SELECT id FROM entity_memories WHERE name = ? AND channel_id IS NULL AND guild_id IS NULL",
                        (name,),
                    )
                elif channel_id is None:
                    check_cursor = await conn.execute(
                        "SELECT id FROM entity_memories WHERE name = ? AND channel_id IS NULL AND guild_id = ?",
                        (name, guild_id),
                    )
                elif guild_id is None:
                    check_cursor = await conn.execute(
                        "SELECT id FROM entity_memories WHERE name = ? AND channel_id = ? AND guild_id IS NULL",
                        (name, channel_id),
                    )
                else:
                    check_cursor = await conn.execute(
                        "SELECT id FROM entity_memories WHERE name = ? AND channel_id = ? AND guild_id = ?",
                        (name, channel_id, guild_id),
                    )
                existing_row = await check_cursor.fetchone()

                try:
                    if existing_row:
                        # UPDATE existing entity (no access_count increment here;
                        # get_entity already incremented it when called before add_entity)
                        existing_id = existing_row[0]
                        await conn.execute(
                            """
                            UPDATE entity_memories SET
                                entity_type = ?,
                                facts = ?,
                                confidence = ?,
                                source = ?,
                                updated_at = ?
                            WHERE id = ?
                            """,
                            (entity_type, facts_json, confidence, source, now, existing_id),
                        )
                        await conn.commit()
                        entity_id = existing_id
                    else:
                        # INSERT new entity
                        cursor = await conn.execute(
                            """
                            INSERT INTO entity_memories (
                                name, entity_type, facts, channel_id, guild_id,
                                confidence, source, created_at, updated_at
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                name,
                                entity_type,
                                facts_json,
                                channel_id,
                                guild_id,
                                confidence,
                                source,
                                now,
                                now,
                            ),
                        )
                        await conn.commit()
                        entity_id = cursor.lastrowid
                except aiosqlite.Error:
                    # Roll back OUR transaction so the pooled connection
                    # doesn't carry an open tx into the next caller.
                    if _own_tx:
                        with contextlib.suppress(aiosqlite.Error):
                            await conn.rollback()
                    raise

            logger.info("🧠 Added/Updated entity: %s (%s)", name, entity_type)
            return entity_id  # type: ignore[no-any-return]

        except aiosqlite.Error:
            logger.exception("Failed to add entity %s", name)
            return None

    async def get_entity(
        self,
        name: str,
        channel_id: int | None = None,
        guild_id: int | None = None,
        update_access: bool = True,
    ) -> Entity | None:
        """Get an entity by name.

        Args:
            update_access: When True (default), bumps access_count for
                ranking. Pass False on read-only paths (prompt assembly,
                contradiction detection) to avoid write amplification.
        """
        if not await self.initialize():
            return None

        # Safety check: ensure db_manager is still available
        if db_manager is None:
            logger.error("Database manager became unavailable")
            return None

        try:
            if not update_access:
                # Read-only fast path — no write connection, no UPDATE.
                async with db_manager.get_connection() as conn:
                    cursor = await conn.execute(
                        """
                        SELECT * FROM entity_memories
                        WHERE name = ? AND (channel_id = ? OR channel_id IS NULL)
                        AND (guild_id = ? OR guild_id IS NULL)
                        ORDER BY (channel_id IS NULL), channel_id DESC,
                                 (guild_id IS NULL), guild_id DESC
                        LIMIT 1
                        """,
                        (name, channel_id, guild_id),
                    )
                    row = await cursor.fetchone()
                    if not row:
                        return None
                    return self._row_to_entity(row)

            # Run read + access_count bump in the SAME write connection so
            # they share a transaction. Previously the read used the read
            # pool and the bump used a fresh write connection, so a delete
            # between them could yield a stale Entity object referencing
            # an id no longer in the DB. Also avoids a write+commit per
            # read on hot lookup paths (we COULD batch these in future,
            # but keeping correctness wins over the WAL churn for now).
            async with db_manager.get_write_connection() as conn:
                cursor = await conn.execute(
                    """
                    SELECT * FROM entity_memories
                    WHERE name = ? AND (channel_id = ? OR channel_id IS NULL)
                    AND (guild_id = ? OR guild_id IS NULL)
                    ORDER BY (channel_id IS NULL), channel_id DESC,
                             (guild_id IS NULL), guild_id DESC
                    LIMIT 1
                    """,
                    (name, channel_id, guild_id),
                )
                row = await cursor.fetchone()
                if not row:
                    return None
                await conn.execute(
                    "UPDATE entity_memories SET access_count = access_count + 1 WHERE id = ?",
                    (row[0],),
                )
                await conn.commit()
                return self._row_to_entity(row)

        except aiosqlite.Error:
            logger.exception("Failed to get entity %s", name)
            return None

    async def search_entities(
        self,
        query: str,
        entity_type: str | None = None,
        channel_id: int | None = None,
        guild_id: int | None = None,
        limit: int = 10,
    ) -> list[Entity]:
        """Search entities by name or facts content."""
        if not await self.initialize():
            return []

        # Safety check: ensure db_manager is available after initialize
        if db_manager is None:
            logger.warning("db_manager became None after initialize")
            return []

        try:
            async with db_manager.get_connection() as conn:
                sql = """
                    SELECT * FROM entity_memories
                    WHERE (name LIKE ? ESCAPE '\\' OR facts LIKE ? ESCAPE '\\')
                """
                # Escape LIKE-special characters to prevent query manipulation
                escaped_query = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                params: list[str | int | None] = [f"%{escaped_query}%", f"%{escaped_query}%"]

                if entity_type:
                    sql += " AND entity_type = ?"
                    params.append(entity_type)

                if channel_id is not None:
                    sql += " AND (channel_id = ? OR channel_id IS NULL)"
                    params.append(channel_id)

                if guild_id is not None:
                    sql += " AND (guild_id = ? OR guild_id IS NULL)"
                    params.append(guild_id)

                sql += " ORDER BY access_count DESC, updated_at DESC LIMIT ?"
                params.append(limit)

                cursor = await conn.execute(sql, params)
                rows = await cursor.fetchall()

                return [self._row_to_entity(row) for row in rows]

        except aiosqlite.Error:
            logger.exception("Failed to search entities")
            return []

    async def update_entity_facts(
        self,
        name: str,
        new_facts: dict[str, Any],
        channel_id: int | None = None,
        guild_id: int | None = None,
        merge: bool = True,
    ) -> bool:
        """Update facts for an existing entity."""
        # update_access=False — we're about to overwrite the row with
        # add_entity below, so the access_count bump from the read path
        # is wasted write amplification and shows up as a hot row in
        # consolidation cycles that touch many entities at once.
        entity = await self.get_entity(name, channel_id, guild_id, update_access=False)
        if not entity:
            return False

        try:
            if merge:
                # Merge with existing facts
                existing = entity.facts.to_dict()
                existing.update(new_facts)
                updated_facts = EntityFacts.from_dict(existing)
            else:
                updated_facts = EntityFacts.from_dict(new_facts)

            # IMPORTANT: scope the upsert to the entity we actually loaded.
            # get_entity does fuzzy NULL-matching (it can return a global/
            # NULL-channel row when a per-channel one is absent), but
            # add_entity's existence check is exact match. Passing the
            # caller's channel_id/guild_id here would create a NEW per-channel
            # row instead of updating the global one, leaving stale facts
            # behind. Use entity.channel_id / entity.guild_id instead.
            return (
                await self.add_entity(
                    name=name,
                    entity_type=entity.entity_type,
                    facts=updated_facts,
                    channel_id=entity.channel_id,
                    guild_id=entity.guild_id,
                    confidence=entity.confidence,
                    source=entity.source,
                )
                is not None
            )

        except (aiosqlite.Error, ValueError):
            logger.exception("Failed to update entity %s", name)
            return False

    async def delete_entity(
        self, name: str, channel_id: int | None = None, guild_id: int | None = None
    ) -> bool:
        """Delete an entity from memory."""
        if not await self.initialize():
            return False
        if db_manager is None:
            return False

        try:
            async with db_manager.get_write_connection() as conn:
                # Use explicit NULL checks consistent with add_entity
                if channel_id is None and guild_id is None:
                    await conn.execute(
                        "DELETE FROM entity_memories WHERE name = ? AND channel_id IS NULL AND guild_id IS NULL",
                        (name,),
                    )
                elif channel_id is None:
                    await conn.execute(
                        "DELETE FROM entity_memories WHERE name = ? AND channel_id IS NULL AND guild_id = ?",
                        (name, guild_id),
                    )
                elif guild_id is None:
                    await conn.execute(
                        "DELETE FROM entity_memories WHERE name = ? AND channel_id = ? AND guild_id IS NULL",
                        (name, channel_id),
                    )
                else:
                    await conn.execute(
                        "DELETE FROM entity_memories WHERE name = ? AND channel_id = ? AND guild_id = ?",
                        (name, channel_id, guild_id),
                    )
                await conn.commit()

            logger.info("🗑️ Deleted entity: %s", name)
            return True

        except aiosqlite.Error:
            logger.exception("Failed to delete entity %s", name)
            return False

    async def get_all_entities(
        self,
        entity_type: str | None = None,
        channel_id: int | None = None,
        guild_id: int | None = None,
        limit: int = 100,
    ) -> list[Entity]:
        """Get all entities, optionally filtered."""
        if not await self.initialize():
            return []
        if db_manager is None:
            return []

        try:
            async with db_manager.get_connection() as conn:
                sql = "SELECT * FROM entity_memories WHERE 1=1"
                params: list[str | int | None] = []

                if entity_type:
                    sql += " AND entity_type = ?"
                    params.append(entity_type)

                if channel_id is not None:
                    sql += " AND (channel_id = ? OR channel_id IS NULL)"
                    params.append(channel_id)

                if guild_id is not None:
                    sql += " AND (guild_id = ? OR guild_id IS NULL)"
                    params.append(guild_id)

                sql += " ORDER BY access_count DESC LIMIT ?"
                params.append(limit)

                cursor = await conn.execute(sql, params)
                rows = await cursor.fetchall()

                return [self._row_to_entity(row) for row in rows]

        except aiosqlite.Error:
            logger.exception("Failed to get all entities")
            return []

    def _row_to_entity(self, row) -> Entity:
        """Convert database row to Entity object.

        Uses named access via ``aiosqlite.Row`` (set as the connection's
        row_factory upstream) so a future schema migration that adds or
        reorders columns can't silently corrupt the Entity by shifting
        positional indices. Falls back to positional access only if the
        row was somehow loaded with a different factory.
        """
        # aiosqlite.Row supports both ``row[idx]`` and ``row["col"]``; using
        # ``in`` to test for a key only works on dict-likes. Try keyed
        # access and fall back to positional for tuple-rows used in tests.
        try:
            facts_raw = row["facts"]
            row_id = row["id"]
        except (IndexError, KeyError, TypeError):
            row_id = row[0]
            facts_raw = row[3]
        try:
            facts_dict = json.loads(facts_raw) if facts_raw else {}
        except (json.JSONDecodeError, TypeError):
            logger.exception(
                "Corrupted JSON in entity row id=%s; falling back to empty facts", row_id
            )
            facts_dict = {}
        try:
            return Entity(
                entity_id=row["id"],
                name=row["name"],
                entity_type=row["entity_type"],
                facts=EntityFacts.from_dict(facts_dict),
                channel_id=row["channel_id"],
                guild_id=row["guild_id"],
                confidence=row["confidence"] or 1.0,
                source=row["source"] or "user",
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                access_count=row["access_count"] or 0,
            )
        except (IndexError, KeyError, TypeError):
            return Entity(
                entity_id=row[0],
                name=row[1],
                entity_type=row[2],
                facts=EntityFacts.from_dict(facts_dict),
                channel_id=row[4],
                guild_id=row[5],
                confidence=row[6] or 1.0,
                source=row[7] or "user",
                created_at=row[8],
                updated_at=row[9],
                access_count=row[10] or 0,
            )

    async def get_entities_for_prompt(
        self, names: list[str], channel_id: int | None = None, guild_id: int | None = None
    ) -> str:
        """Get formatted entity information for prompt injection."""
        entities = []
        for name in names:
            # Skip access_count bump on the prompt-assembly hot path —
            # this fires on every message and was generating a write per
            # entity per turn.
            entity = await self.get_entity(name, channel_id, guild_id, update_access=False)
            if entity:
                entities.append(entity)

        if not entities:
            return ""

        lines = ["[ข้อมูลตัวละคร/สถานที่ที่เกี่ยวข้อง - ต้องใช้ข้อมูลนี้ในการตอบ]"]
        for entity in entities:
            lines.append(entity.to_prompt_text())
            lines.append("")

        return "\n".join(lines)


# Global instance
entity_memory = EntityMemoryManager()
