"""
Tests for cogs.ai_core.memory.entity_memory module.
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestEntityFactsDataclass:
    """Tests for EntityFacts dataclass."""

    def test_create_entity_facts(self):
        """Test creating EntityFacts."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(description="A test entity")

        assert facts.description == "A test entity"
        assert facts.age is None

    def test_entity_facts_with_character_fields(self):
        """Test EntityFacts with character-specific fields."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(
            description="A character",
            age=25,
            occupation="Student",
            personality="Friendly",
            appearance="Tall with dark hair"
        )

        assert facts.age == 25
        assert facts.occupation == "Student"
        assert facts.personality == "Friendly"

    def test_entity_facts_with_relationships(self):
        """Test EntityFacts with relationships."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(
            relationships={"Alice": "friend", "Bob": "sibling"}
        )

        assert facts.relationships["Alice"] == "friend"
        assert facts.relationships["Bob"] == "sibling"

    def test_entity_facts_to_dict(self):
        """Test EntityFacts to_dict method."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(
            description="Test description",
            age=30,
            occupation="Teacher"
        )

        result = facts.to_dict()

        assert result["description"] == "Test description"
        assert result["age"] == 30
        # None values should be excluded
        assert "personality" not in result or result.get("personality") is None

    def test_entity_facts_from_dict(self):
        """Test EntityFacts from_dict method."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        data = {
            "description": "Test entity",
            "age": 25,
            "occupation": "Engineer"
        }

        facts = EntityFacts.from_dict(data)

        assert facts.description == "Test entity"
        assert facts.age == 25
        assert facts.occupation == "Engineer"

    def test_entity_facts_from_dict_with_custom_fields(self):
        """Test EntityFacts from_dict with custom fields."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        data = {
            "description": "Test",
            "custom_field": "custom_value"
        }

        facts = EntityFacts.from_dict(data)

        assert facts.description == "Test"
        assert facts.custom.get("custom_field") == "custom_value"

    def test_entity_facts_to_prompt_text(self):
        """Test EntityFacts to_prompt_text method."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(
            description="A mysterious person",
            age=30,
            occupation="Detective"
        )

        result = facts.to_prompt_text()

        assert "A mysterious person" in result
        assert "30" in result
        assert "Detective" in result


class TestEntityDataclass:
    """Tests for Entity dataclass."""

    def test_create_entity(self):
        """Test creating Entity."""
        from cogs.ai_core.memory.entity_memory import Entity, EntityFacts

        facts = EntityFacts(description="Test character")
        entity = Entity(
            entity_id=1,
            name="Faust",
            entity_type="character",
            facts=facts
        )

        assert entity.name == "Faust"
        assert entity.entity_type == "character"
        assert entity.confidence == 1.0

    def test_entity_to_prompt_text(self):
        """Test Entity to_prompt_text method."""
        from cogs.ai_core.memory.entity_memory import Entity, EntityFacts

        facts = EntityFacts(description="A wise person")
        entity = Entity(
            entity_id=1,
            name="Sage",
            entity_type="character",
            facts=facts
        )

        result = entity.to_prompt_text()

        assert "CHARACTER" in result
        assert "Sage" in result
        assert "wise person" in result

    def test_entity_default_values(self):
        """Test Entity default values."""
        from cogs.ai_core.memory.entity_memory import Entity, EntityFacts

        facts = EntityFacts()
        entity = Entity(
            entity_id=1,
            name="Test",
            entity_type="item",
            facts=facts
        )

        assert entity.confidence == 1.0
        assert entity.source == "user"
        assert entity.access_count == 0
        assert entity.channel_id is None


class TestEntityMemoryManager:
    """Tests for EntityMemoryManager class."""

    def test_create_manager(self):
        """Test creating EntityMemoryManager."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        manager = EntityMemoryManager()

        assert manager is not None
        assert manager._initialized is False

    def test_create_table_sql_exists(self):
        """Test CREATE_TABLE_SQL constant exists."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        manager = EntityMemoryManager()

        assert "entity_memories" in manager.CREATE_TABLE_SQL

    def test_create_index_sql_exists(self):
        """Test CREATE_INDEX_SQL constant exists."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        manager = EntityMemoryManager()

        assert "idx_entity_name" in manager.CREATE_INDEX_SQL


class TestEntityMemoryManagerMocked:
    """Tests for EntityMemoryManager with mocked database."""

    @pytest.mark.asyncio
    async def test_initialize_already_initialized(self):
        """Test initialize returns True when already initialized."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        manager = EntityMemoryManager()
        manager._initialized = True

        result = await manager.initialize()

        assert result is True

    def test_manager_initialized_flag(self):
        """Test manager starts with _initialized False."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        manager = EntityMemoryManager()

        assert manager._initialized is False


class TestGlobalEntityMemory:
    """Tests for global entity_memory instance."""

    def test_global_instance_exists(self):
        """Test global entity_memory exists."""
        from cogs.ai_core.memory.entity_memory import entity_memory

        assert entity_memory is not None

    def test_global_instance_is_manager(self):
        """Test global entity_memory is EntityMemoryManager."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager, entity_memory

        assert isinstance(entity_memory, EntityMemoryManager)


class TestEntityFactsLocationFields:
    """Tests for EntityFacts location-specific fields."""

    def test_location_fields(self):
        """Test location-specific fields."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(
            location_type="apartment",
            address="123 Main Street"
        )

        assert facts.location_type == "apartment"
        assert facts.address == "123 Main Street"

    def test_location_to_prompt_text(self):
        """Test location fields in prompt text."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(
            location_type="cafe",
            address="Downtown Area"
        )

        result = facts.to_prompt_text()

        assert "cafe" in result
        assert "Downtown Area" in result


class TestEntityFactsItemFields:
    """Tests for EntityFacts item-specific fields."""

    def test_item_fields(self):
        """Test item-specific fields."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(
            owner="Alice",
            item_type="weapon"
        )

        assert facts.owner == "Alice"
        assert facts.item_type == "weapon"


class TestEntityFactsCustomFields:
    """Tests for EntityFacts custom fields."""

    def test_custom_fields(self):
        """Test custom fields dictionary."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(
            custom={"special_ability": "teleport", "power_level": 9000}
        )

        assert facts.custom["special_ability"] == "teleport"
        assert facts.custom["power_level"] == 9000

    def test_custom_fields_in_prompt(self):
        """Test custom fields appear in prompt text."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(
            custom={"special_ability": "teleportation"}
        )

        result = facts.to_prompt_text()

        assert "special_ability" in result
        assert "teleportation" in result
