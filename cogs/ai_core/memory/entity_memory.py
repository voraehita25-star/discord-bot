"""
Entity Memory System
Stores and retrieves structured entity information (characters, locations, items).
Prevents AI from hallucinating facts by providing verified entity data.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

# Database manager
try:
    from utils.database import db as db_manager
except ImportError:
    db_manager = None


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
        """Convert to dictionary, excluding None values."""
        result = {}
        for key, value in asdict(self).items():
            if value is not None and value not in ({}, []):
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
        lines = []
        if self.description:
            lines.append(f"คำอธิบาย: {self.description}")
        if self.age:
            lines.append(f"อายุ: {self.age} ปี")
        if self.occupation:
            lines.append(f"อาชีพ: {self.occupation}")
        if self.personality:
            lines.append(f"นิสัย: {self.personality}")
        if self.appearance:
            lines.append(f"รูปลักษณ์: {self.appearance}")
        if self.relationships:
            rel_str = ", ".join([f"{k}: {v}" for k, v in self.relationships.items()])
            lines.append(f"ความสัมพันธ์: {rel_str}")
        if self.location_type:
            lines.append(f"ประเภทสถานที่: {self.location_type}")
        if self.address:
            lines.append(f"ที่อยู่: {self.address}")
        if self.owner:
            lines.append(f"เจ้าของ: {self.owner}")
        if self.custom:
            for k, v in self.custom.items():
                lines.append(f"{k}: {v}")
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
        """Convert to text for prompt injection."""
        facts_text = self.facts.to_prompt_text()
        return f"[{self.entity_type.upper()}] {self.name}:\n{facts_text}"


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
    """

    def __init__(self):
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the entity memory table."""
        if self._initialized or not db_manager:
            return self._initialized

        try:
            async with db_manager.get_connection() as conn:
                await conn.execute(self.CREATE_TABLE_SQL)
                for sql in self.CREATE_INDEX_SQL.strip().split(";"):
                    if sql.strip():
                        await conn.execute(sql)
                await conn.commit()
            self._initialized = True
            logging.info("🧠 Entity Memory table initialized")
            return True
        except Exception as e:
            logging.error("Failed to initialize entity memory table: %s", e)
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

        try:
            now = time.time()
            facts_json = json.dumps(facts.to_dict(), ensure_ascii=False)

            async with db_manager.get_connection() as conn:
                cursor = await conn.execute(
                    """
                    INSERT INTO entity_memories (
                        name, entity_type, facts, channel_id, guild_id,
                        confidence, source, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(name, channel_id, guild_id) DO UPDATE SET
                        facts = excluded.facts,
                        confidence = excluded.confidence,
                        source = excluded.source,
                        updated_at = excluded.updated_at,
                        access_count = access_count + 1
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

            logging.info("🧠 Added/Updated entity: %s (%s)", name, entity_type)
            return entity_id

        except Exception as e:
            logging.error("Failed to add entity %s: %s", name, e)
            return None

    async def get_entity(
        self, name: str, channel_id: int | None = None, guild_id: int | None = None
    ) -> Entity | None:
        """Get an entity by name."""
        if not await self.initialize():
            return None

        try:
            async with db_manager.get_connection() as conn:
                # First try exact match with channel/guild
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

                if row:
                    # Update access count
                    await conn.execute(
                        "UPDATE entity_memories SET access_count = access_count + 1 WHERE id = ?",
                        (row[0],),
                    )
                    await conn.commit()

                    return self._row_to_entity(row)

            return None

        except Exception as e:
            logging.error("Failed to get entity %s: %s", name, e)
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

        try:
            async with db_manager.get_connection() as conn:
                sql = """
                    SELECT * FROM entity_memories
                    WHERE (name LIKE ? OR facts LIKE ?)
                """
                params = [f"%{query}%", f"%{query}%"]

                if entity_type:
                    sql += " AND entity_type = ?"
                    params.append(entity_type)

                if channel_id:
                    sql += " AND (channel_id = ? OR channel_id IS NULL)"
                    params.append(channel_id)

                if guild_id:
                    sql += " AND (guild_id = ? OR guild_id IS NULL)"
                    params.append(guild_id)

                sql += " ORDER BY access_count DESC, updated_at DESC LIMIT ?"
                params.append(limit)

                cursor = await conn.execute(sql, params)
                rows = await cursor.fetchall()

                return [self._row_to_entity(row) for row in rows]

        except Exception as e:
            logging.error("Failed to search entities: %s", e)
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
        entity = await self.get_entity(name, channel_id, guild_id)
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

            return (
                await self.add_entity(
                    name=name,
                    entity_type=entity.entity_type,
                    facts=updated_facts,
                    channel_id=channel_id,
                    guild_id=guild_id,
                    confidence=entity.confidence,
                    source=entity.source,
                )
                is not None
            )

        except Exception as e:
            logging.error("Failed to update entity %s: %s", name, e)
            return False

    async def delete_entity(
        self, name: str, channel_id: int | None = None, guild_id: int | None = None
    ) -> bool:
        """Delete an entity from memory."""
        if not await self.initialize():
            return False

        try:
            async with db_manager.get_connection() as conn:
                await conn.execute(
                    """
                    DELETE FROM entity_memories
                    WHERE name = ? AND channel_id IS ? AND guild_id IS ?
                    """,
                    (name, channel_id, guild_id),
                )
                await conn.commit()

            logging.info("🗑️ Deleted entity: %s", name)
            return True

        except Exception as e:
            logging.error("Failed to delete entity %s: %s", name, e)
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

        try:
            async with db_manager.get_connection() as conn:
                sql = "SELECT * FROM entity_memories WHERE 1=1"
                params = []

                if entity_type:
                    sql += " AND entity_type = ?"
                    params.append(entity_type)

                if channel_id:
                    sql += " AND (channel_id = ? OR channel_id IS NULL)"
                    params.append(channel_id)

                if guild_id:
                    sql += " AND (guild_id = ? OR guild_id IS NULL)"
                    params.append(guild_id)

                sql += " ORDER BY access_count DESC LIMIT ?"
                params.append(limit)

                cursor = await conn.execute(sql, params)
                rows = await cursor.fetchall()

                return [self._row_to_entity(row) for row in rows]

        except Exception as e:
            logging.error("Failed to get all entities: %s", e)
            return []

    def _row_to_entity(self, row) -> Entity:
        """Convert database row to Entity object."""
        facts_dict = json.loads(row[3]) if row[3] else {}
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
            entity = await self.get_entity(name, channel_id, guild_id)
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
