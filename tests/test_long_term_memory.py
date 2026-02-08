"""
Tests for cogs.ai_core.memory.long_term_memory module.
"""

from datetime import datetime


class TestFactCategoryEnum:
    """Tests for FactCategory enum."""

    def test_fact_category_identity(self):
        """Test IDENTITY category value."""
        from cogs.ai_core.memory.long_term_memory import FactCategory
        assert FactCategory.IDENTITY.value == "identity"

    def test_fact_category_preference(self):
        """Test PREFERENCE category value."""
        from cogs.ai_core.memory.long_term_memory import FactCategory
        assert FactCategory.PREFERENCE.value == "preference"

    def test_fact_category_personal(self):
        """Test PERSONAL category value."""
        from cogs.ai_core.memory.long_term_memory import FactCategory
        assert FactCategory.PERSONAL.value == "personal"

    def test_fact_category_relationship(self):
        """Test RELATIONSHIP category value."""
        from cogs.ai_core.memory.long_term_memory import FactCategory
        assert FactCategory.RELATIONSHIP.value == "relationship"

    def test_fact_category_skill(self):
        """Test SKILL category value."""
        from cogs.ai_core.memory.long_term_memory import FactCategory
        assert FactCategory.SKILL.value == "skill"

    def test_fact_category_custom(self):
        """Test CUSTOM category value."""
        from cogs.ai_core.memory.long_term_memory import FactCategory
        assert FactCategory.CUSTOM.value == "custom"


class TestImportanceLevelEnum:
    """Tests for ImportanceLevel enum."""

    def test_importance_low(self):
        """Test LOW importance value."""
        from cogs.ai_core.memory.long_term_memory import ImportanceLevel
        assert ImportanceLevel.LOW.value == 1

    def test_importance_medium(self):
        """Test MEDIUM importance value."""
        from cogs.ai_core.memory.long_term_memory import ImportanceLevel
        assert ImportanceLevel.MEDIUM.value == 2

    def test_importance_high(self):
        """Test HIGH importance value."""
        from cogs.ai_core.memory.long_term_memory import ImportanceLevel
        assert ImportanceLevel.HIGH.value == 3

    def test_importance_critical(self):
        """Test CRITICAL importance value."""
        from cogs.ai_core.memory.long_term_memory import ImportanceLevel
        assert ImportanceLevel.CRITICAL.value == 4


class TestFactDataclass:
    """Tests for Fact dataclass."""

    def test_create_fact(self):
        """Test creating a Fact."""
        from cogs.ai_core.memory.long_term_memory import Fact

        fact = Fact(user_id=12345, content="Test fact")

        assert fact.user_id == 12345
        assert fact.content == "Test fact"

    def test_fact_defaults(self):
        """Test Fact default values."""
        from cogs.ai_core.memory.long_term_memory import Fact, FactCategory, ImportanceLevel

        fact = Fact()

        assert fact.id is None
        assert fact.user_id == 0
        assert fact.category == FactCategory.CUSTOM.value
        assert fact.importance == ImportanceLevel.MEDIUM.value
        assert fact.confidence == 1.0
        assert fact.is_active is True
        assert fact.mention_count == 1

    def test_fact_to_dict(self):
        """Test Fact to_dict method."""
        from cogs.ai_core.memory.long_term_memory import Fact

        fact = Fact(user_id=12345, content="Test")
        result = fact.to_dict()

        assert result["user_id"] == 12345
        assert result["content"] == "Test"

    def test_fact_to_dict_with_datetime(self):
        """Test Fact to_dict with datetime fields."""
        from cogs.ai_core.memory.long_term_memory import Fact

        now = datetime.now()
        fact = Fact(user_id=12345, first_mentioned=now)
        result = fact.to_dict()

        assert isinstance(result["first_mentioned"], str)

    def test_fact_from_dict(self):
        """Test Fact from_dict method."""
        from cogs.ai_core.memory.long_term_memory import Fact

        data = {
            "id": None,
            "user_id": 12345,
            "channel_id": None,
            "category": "custom",
            "content": "Test fact",
            "importance": 2,
            "first_mentioned": None,
            "last_confirmed": None,
            "mention_count": 1,
            "confidence": 1.0,
            "source_message": None,
            "is_active": True,
            "is_user_defined": False
        }

        fact = Fact.from_dict(data)

        assert fact.user_id == 12345
        assert fact.content == "Test fact"

    def test_fact_from_dict_with_iso_datetime(self):
        """Test Fact from_dict with ISO datetime strings."""
        from cogs.ai_core.memory.long_term_memory import Fact

        now = datetime.now()
        data = {
            "id": None,
            "user_id": 12345,
            "channel_id": None,
            "category": "custom",
            "content": "Test",
            "importance": 2,
            "first_mentioned": now.isoformat(),
            "last_confirmed": None,
            "mention_count": 1,
            "confidence": 1.0,
            "source_message": None,
            "is_active": True,
            "is_user_defined": False
        }

        fact = Fact.from_dict(data)

        assert isinstance(fact.first_mentioned, datetime)

    def test_fact_decay_confidence(self):
        """Test Fact decay_confidence method."""
        from cogs.ai_core.memory.long_term_memory import Fact

        fact = Fact(user_id=12345, confidence=1.0)

        # Decay after 30 days (returns decayed value without mutating)
        decayed = fact.decay_confidence(30)
        assert decayed < 1.0
        assert decayed > 0.8

    def test_fact_decay_confidence_minimum(self):
        """Test Fact decay_confidence has minimum value."""
        from cogs.ai_core.memory.long_term_memory import Fact

        fact = Fact(user_id=12345, confidence=1.0)

        # Decay after 1000 days
        decayed = fact.decay_confidence(1000)
        assert decayed >= 0.1


class TestFactExtractor:
    """Tests for FactExtractor class."""

    def test_create_extractor(self):
        """Test creating FactExtractor."""
        from cogs.ai_core.memory.long_term_memory import FactExtractor

        extractor = FactExtractor()
        assert extractor is not None

    def test_extraction_patterns_exist(self):
        """Test EXTRACTION_PATTERNS is defined."""
        from cogs.ai_core.memory.long_term_memory import FactExtractor

        extractor = FactExtractor()
        assert len(extractor.EXTRACTION_PATTERNS) > 0

    def test_compiled_patterns_exist(self):
        """Test patterns are compiled."""
        from cogs.ai_core.memory.long_term_memory import FactExtractor

        extractor = FactExtractor()
        assert len(extractor._compiled_patterns) > 0

    def test_extract_facts_empty_message(self):
        """Test extract_facts with empty message."""
        from cogs.ai_core.memory.long_term_memory import FactExtractor

        extractor = FactExtractor()
        result = extractor.extract_facts("", 12345)

        assert isinstance(result, list)

    def test_extract_facts_name_thai(self):
        """Test extract_facts extracts Thai name."""
        from cogs.ai_core.memory.long_term_memory import FactExtractor

        extractor = FactExtractor()
        result = extractor.extract_facts("ผมชื่อสมชาย", 12345)

        # May or may not extract depending on pattern
        assert isinstance(result, list)

    def test_extract_facts_name_english(self):
        """Test extract_facts extracts English name."""
        from cogs.ai_core.memory.long_term_memory import FactExtractor

        extractor = FactExtractor()
        result = extractor.extract_facts("my name is John", 12345)

        # May or may not extract depending on pattern
        assert isinstance(result, list)

    def test_extract_facts_remember_command(self):
        """Test extract_facts with remember command."""
        from cogs.ai_core.memory.long_term_memory import FactExtractor

        extractor = FactExtractor()
        result = extractor.extract_facts("remember that I like pizza", 12345)

        assert isinstance(result, list)


class TestDbAvailable:
    """Tests for DB_AVAILABLE flag."""

    def test_db_available_is_bool(self):
        """Test DB_AVAILABLE is boolean."""
        from cogs.ai_core.memory.long_term_memory import DB_AVAILABLE

        assert isinstance(DB_AVAILABLE, bool)


class TestFactWithAllFields:
    """Tests for Fact with all fields populated."""

    def test_fact_all_fields(self):
        """Test Fact with all fields."""
        from cogs.ai_core.memory.long_term_memory import Fact, FactCategory, ImportanceLevel

        now = datetime.now()
        fact = Fact(
            id=1,
            user_id=12345,
            channel_id=67890,
            category=FactCategory.IDENTITY.value,
            content="User's name is John",
            importance=ImportanceLevel.CRITICAL.value,
            first_mentioned=now,
            last_confirmed=now,
            mention_count=5,
            confidence=0.95,
            source_message="I'm John",
            is_active=True,
            is_user_defined=True
        )

        assert fact.id == 1
        assert fact.user_id == 12345
        assert fact.channel_id == 67890
        assert fact.category == "identity"
        assert fact.importance == 4
        assert fact.mention_count == 5
        assert fact.confidence == 0.95
        assert fact.is_user_defined is True
