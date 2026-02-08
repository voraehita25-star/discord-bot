"""
Extended tests for Long-term Memory module.
Tests Fact dataclass and related enums.
"""

from datetime import datetime

import pytest


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

    def test_module_has_docstring(self):
        """Test long_term_memory module has docstring."""
        try:
            from cogs.ai_core.memory import long_term_memory
        except ImportError:
            pytest.skip("long_term_memory not available")
            return

        assert long_term_memory.__doc__ is not None


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
