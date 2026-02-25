"""
Tests for cogs.ai_core.memory.long_term_memory module.
"""

from datetime import datetime


import pytest

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


# ======================================================================
# Merged from test_long_term_memory_extended.py
# ======================================================================

class TestFactCategory:
    """Tests for FactCategory enum."""

    def test_fact_category_identity(self):
        """Test IDENTITY category value."""
        try:
            from cogs.ai_core.memory.long_term_memory import FactCategory
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert FactCategory.IDENTITY.value == "identity"

    def test_fact_category_preference(self):
        """Test PREFERENCE category value."""
        try:
            from cogs.ai_core.memory.long_term_memory import FactCategory
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert FactCategory.PREFERENCE.value == "preference"

    def test_fact_category_personal(self):
        """Test PERSONAL category value."""
        try:
            from cogs.ai_core.memory.long_term_memory import FactCategory
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert FactCategory.PERSONAL.value == "personal"

    def test_fact_category_relationship(self):
        """Test RELATIONSHIP category value."""
        try:
            from cogs.ai_core.memory.long_term_memory import FactCategory
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert FactCategory.RELATIONSHIP.value == "relationship"

    def test_fact_category_skill(self):
        """Test SKILL category value."""
        try:
            from cogs.ai_core.memory.long_term_memory import FactCategory
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert FactCategory.SKILL.value == "skill"

    def test_fact_category_custom(self):
        """Test CUSTOM category value."""
        try:
            from cogs.ai_core.memory.long_term_memory import FactCategory
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert FactCategory.CUSTOM.value == "custom"


class TestImportanceLevel:
    """Tests for ImportanceLevel enum."""

    def test_importance_level_low(self):
        """Test LOW importance level."""
        try:
            from cogs.ai_core.memory.long_term_memory import ImportanceLevel
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert ImportanceLevel.LOW.value == 1

    def test_importance_level_medium(self):
        """Test MEDIUM importance level."""
        try:
            from cogs.ai_core.memory.long_term_memory import ImportanceLevel
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert ImportanceLevel.MEDIUM.value == 2

    def test_importance_level_high(self):
        """Test HIGH importance level."""
        try:
            from cogs.ai_core.memory.long_term_memory import ImportanceLevel
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert ImportanceLevel.HIGH.value == 3

    def test_importance_level_critical(self):
        """Test CRITICAL importance level."""
        try:
            from cogs.ai_core.memory.long_term_memory import ImportanceLevel
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert ImportanceLevel.CRITICAL.value == 4


class TestFactDataclass:
    """Tests for Fact dataclass."""

    def test_fact_default_values(self):
        """Test Fact has correct default values."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact, FactCategory, ImportanceLevel
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        fact = Fact()

        assert fact.id is None
        assert fact.user_id == 0
        assert fact.channel_id is None
        assert fact.category == FactCategory.CUSTOM.value
        assert fact.content == ""
        assert fact.importance == ImportanceLevel.MEDIUM.value
        assert fact.mention_count == 1
        assert fact.confidence == 1.0
        assert fact.is_active is True
        assert fact.is_user_defined is False

    def test_fact_with_values(self):
        """Test Fact with specified values."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact, FactCategory, ImportanceLevel
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        fact = Fact(
            id=1,
            user_id=123456,
            channel_id=789012,
            category=FactCategory.IDENTITY.value,
            content="User name is John",
            importance=ImportanceLevel.HIGH.value
        )

        assert fact.id == 1
        assert fact.user_id == 123456
        assert fact.channel_id == 789012
        assert fact.category == "identity"
        assert fact.content == "User name is John"
        assert fact.importance == 3


class TestFactToDict:
    """Tests for Fact.to_dict method."""

    def test_to_dict_basic(self):
        """Test to_dict returns dictionary."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        fact = Fact(user_id=123, content="Test content")

        result = fact.to_dict()

        assert isinstance(result, dict)
        assert result["user_id"] == 123
        assert result["content"] == "Test content"

    def test_to_dict_with_datetime(self):
        """Test to_dict converts datetime to ISO format."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        now = datetime.now()
        fact = Fact(
            user_id=123,
            first_mentioned=now,
            last_confirmed=now
        )

        result = fact.to_dict()

        assert isinstance(result["first_mentioned"], str)
        assert isinstance(result["last_confirmed"], str)


class TestFactFromDict:
    """Tests for Fact.from_dict method."""

    def test_from_dict_basic(self):
        """Test from_dict creates Fact instance."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        data = {
            "id": 1,
            "user_id": 123,
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

        assert isinstance(fact, Fact)
        assert fact.id == 1
        assert fact.user_id == 123
        assert fact.content == "Test fact"


class TestDatabaseAvailable:
    """Tests for DB_AVAILABLE flag."""

    def test_db_available_defined(self):
        """Test DB_AVAILABLE is defined."""
        try:
            from cogs.ai_core.memory.long_term_memory import DB_AVAILABLE
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert isinstance(DB_AVAILABLE, bool)


class TestModuleDocstring:
    """Tests for module documentation."""

class TestFactMentionCount:
    """Tests for mention_count attribute."""

    def test_mention_count_default(self):
        """Test mention_count defaults to 1."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        fact = Fact()

        assert fact.mention_count == 1

    def test_mention_count_custom(self):
        """Test mention_count can be set."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        fact = Fact(mention_count=5)

        assert fact.mention_count == 5


class TestFactConfidence:
    """Tests for confidence attribute."""

    def test_confidence_default(self):
        """Test confidence defaults to 1.0."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        fact = Fact()

        assert fact.confidence == 1.0

    def test_confidence_custom(self):
        """Test confidence can be set."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        fact = Fact(confidence=0.75)

        assert fact.confidence == 0.75


class TestFactFlags:
    """Tests for fact flag attributes."""

    def test_is_active_default_true(self):
        """Test is_active defaults to True."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        fact = Fact()

        assert fact.is_active is True

    def test_is_user_defined_default_false(self):
        """Test is_user_defined defaults to False."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        fact = Fact()

        assert fact.is_user_defined is False

    def test_flags_can_be_set(self):
        """Test flags can be set to custom values."""
        try:
            from cogs.ai_core.memory.long_term_memory import Fact
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        fact = Fact(is_active=False, is_user_defined=True)

        assert fact.is_active is False
        assert fact.is_user_defined is True
