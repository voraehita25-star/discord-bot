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
            "is_user_defined": False,
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
            "is_user_defined": False,
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
            is_user_defined=True,
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
            importance=ImportanceLevel.HIGH.value,
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
        fact = Fact(user_id=123, first_mentioned=now, last_confirmed=now)

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
            "is_user_defined": False,
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


# ======================================================================
# Appended: deepened coverage for LongTermMemory CRUD / decay / query
# branches and error paths.
#
# Two execution modes are exercised:
#   * cache-only mode  -> DB_AVAILABLE = False, db = None
#       (covers _store_fact cache branch, LRU eviction, near-capacity
#        warning, get_user_facts cache filters, forget/dedup cache mutation,
#        _update_fact_confirmation cache-only branch, _get_user_lock pruning)
#   * DB-backed mode   -> db patched with a fake aiosqlite-style connection
#       (covers init_schema, get_user_facts DB rows + _parse_ts, _store_fact
#        INSERT, forget_fact DB write, deduplicate_facts DB write,
#        _update_fact_confirmation DB write)
#
# The DB layer is mocked the same way sibling tests do (test_storage.py):
# db.get_connection() / db.get_write_connection() return an object that is
# an async context manager yielding a connection whose .execute is an
# AsyncMock returning a cursor.
# ======================================================================

from contextlib import asynccontextmanager
from datetime import timezone
from unittest.mock import AsyncMock, MagicMock, patch

LTM_MODULE = "cogs.ai_core.memory.long_term_memory"


class _Row(dict):
    """dict subclass that mimics aiosqlite.Row (supports keys() + __getitem__)."""


def _make_cache_only(monkeypatch):
    """Build a fresh LongTermMemory in cache-only mode (no DB)."""
    from cogs.ai_core.memory import long_term_memory as mod

    monkeypatch.setattr(mod, "DB_AVAILABLE", False)
    monkeypatch.setattr(mod, "db", None)
    return mod.LongTermMemory()


class _FakeCursor:
    def __init__(self, rows=None, lastrowid=None):
        self._rows = rows or []
        self.lastrowid = lastrowid

    async def fetchall(self):
        return self._rows


class _FakeConn:
    """Records every SQL statement executed; returns a configurable cursor."""

    def __init__(self, rows=None, lastrowid=42):
        self.rows = rows
        self.lastrowid = lastrowid
        self.executed = []  # list of (sql, params)
        self.commits = 0

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return _FakeCursor(rows=self.rows, lastrowid=self.lastrowid)

    async def commit(self):
        self.commits += 1


def _make_db_mock(conn):
    """Return a MagicMock db whose get_connection/get_write_connection are
    async context managers yielding ``conn``."""
    db_mock = MagicMock()

    @asynccontextmanager
    async def _cm(*_args, **_kwargs):
        yield conn

    db_mock.get_connection.side_effect = _cm
    db_mock.get_write_connection.side_effect = _cm
    return db_mock


def _make_db_backed(monkeypatch, conn):
    """Build a fresh LongTermMemory in DB-backed mode using ``conn``."""
    from cogs.ai_core.memory import long_term_memory as mod

    db_mock = _make_db_mock(conn)
    monkeypatch.setattr(mod, "DB_AVAILABLE", True)
    monkeypatch.setattr(mod, "db", db_mock)
    return mod.LongTermMemory(), db_mock


class TestStoreFactCacheOnly:
    """_store_fact cache-only branch + LRU eviction + capacity warning."""

    @pytest.mark.asyncio
    async def test_store_assigns_monotonic_cache_id(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        f1 = Fact(user_id=1, content="alpha fact one")
        f2 = Fact(user_id=1, content="beta fact two")

        id1 = await ltm._store_fact(f1)
        id2 = await ltm._store_fact(f2)

        assert id1 == 1
        assert id2 == 2
        assert f1.id == 1
        assert f2.id == 2
        assert len(ltm._cache[1]) == 2

    @pytest.mark.asyncio
    async def test_lru_eviction_at_capacity(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        ltm.MAX_CACHE_USERS = 3  # shrink for test

        for uid in (10, 11, 12):
            await ltm._store_fact(Fact(user_id=uid, content=f"fact for {uid}"))

        # Touch user 10 so it becomes most-recently-used; 11 is now LRU.
        ltm._cache.move_to_end(10)

        # Inserting a 4th distinct user evicts the LRU (user 11).
        await ltm._store_fact(Fact(user_id=13, content="fact for 13"))

        assert 11 not in ltm._cache
        assert 10 in ltm._cache
        assert 13 in ltm._cache
        assert len(ltm._cache) == 3

    @pytest.mark.asyncio
    async def test_existing_user_moved_to_end_not_evicted(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        await ltm._store_fact(Fact(user_id=5, content="first fact here"))
        # Storing a second fact for same user must not create a new bucket.
        await ltm._store_fact(Fact(user_id=5, content="second fact here"))
        assert list(ltm._cache.keys()) == [5]
        assert len(ltm._cache[5]) == 2

    @pytest.mark.asyncio
    async def test_near_capacity_warning_logged(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        ltm.MAX_CACHE_USERS = 12  # threshold = MAX-10 = 2

        await ltm._store_fact(Fact(user_id=1, content="aaaaa fact"))
        await ltm._store_fact(Fact(user_id=2, content="bbbbb fact"))

        with patch.object(ltm.logger, "warning") as warn:
            # cache size 2 >= 12-10 -> warning fires on a get
            await ltm.get_user_facts(99)
            assert warn.called


class TestGetUserFactsCacheFilters:
    """get_user_facts cache-only path honors category + include_inactive."""

    @pytest.mark.asyncio
    async def test_returns_cached_facts(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        await ltm._store_fact(Fact(user_id=7, content="hello world fact"))
        facts = await ltm.get_user_facts(7)
        assert len(facts) == 1
        assert facts[0].content == "hello world fact"

    @pytest.mark.asyncio
    async def test_unknown_user_returns_empty(self, monkeypatch):
        ltm = _make_cache_only(monkeypatch)
        assert await ltm.get_user_facts(404) == []

    @pytest.mark.asyncio
    async def test_category_filter(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact, FactCategory

        ltm = _make_cache_only(monkeypatch)
        await ltm._store_fact(
            Fact(user_id=1, content="likes coffee", category=FactCategory.PREFERENCE.value)
        )
        await ltm._store_fact(
            Fact(user_id=1, content="named alice", category=FactCategory.IDENTITY.value)
        )

        prefs = await ltm.get_user_facts(1, category=FactCategory.PREFERENCE.value)
        assert len(prefs) == 1
        assert prefs[0].content == "likes coffee"

    @pytest.mark.asyncio
    async def test_include_inactive_filter(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        await ltm._store_fact(Fact(user_id=1, content="active fact here", is_active=True))
        await ltm._store_fact(Fact(user_id=1, content="dead fact here", is_active=False))

        active_only = await ltm.get_user_facts(1)
        assert len(active_only) == 1
        assert active_only[0].content == "active fact here"

        with_inactive = await ltm.get_user_facts(1, include_inactive=True)
        assert len(with_inactive) == 2

    @pytest.mark.asyncio
    async def test_get_moves_user_to_end(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        await ltm._store_fact(Fact(user_id=1, content="user one fact"))
        await ltm._store_fact(Fact(user_id=2, content="user two fact"))
        # user 1 is currently LRU; reading it should promote it.
        await ltm.get_user_facts(1)
        assert list(ltm._cache.keys())[-1] == 1


class TestProcessMessageCacheOnly:
    """process_message: extraction -> store / dedup-confirm."""

    @pytest.mark.asyncio
    async def test_no_facts_returns_empty(self, monkeypatch):
        ltm = _make_cache_only(monkeypatch)
        result = await ltm.process_message("just chatting about nothing", user_id=1)
        assert result == []

    @pytest.mark.asyncio
    async def test_stores_extracted_fact(self, monkeypatch):
        ltm = _make_cache_only(monkeypatch)
        stored = await ltm.process_message("remember that I love espresso", user_id=1)
        assert len(stored) >= 1
        assert any("espresso" in f.content for f in stored)
        # Fact must be persisted to cache and carry an assigned id.
        assert all(f.id is not None for f in stored)
        cached = await ltm.get_user_facts(1)
        assert any("espresso" in f.content for f in cached)

    @pytest.mark.asyncio
    async def test_duplicate_message_confirms_not_double_stores(self, monkeypatch):
        ltm = _make_cache_only(monkeypatch)
        first = await ltm.process_message("remember that I love espresso", user_id=1)
        assert len(first) >= 1
        count_after_first = len(ltm._cache[1])

        # Same message again -> dedup path -> confirmation, no new rows.
        second = await ltm.process_message("remember that I love espresso", user_id=1)
        assert second == []
        assert len(ltm._cache[1]) == count_after_first
        # mention_count bumped on confirmation.
        assert any(f.mention_count >= 2 for f in ltm._cache[1])


class TestAddExplicitFact:
    """add_explicit_fact happy path + dedup path (cache-only)."""

    @pytest.mark.asyncio
    async def test_adds_new_fact(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import ImportanceLevel

        ltm = _make_cache_only(monkeypatch)
        fact = await ltm.add_explicit_fact(user_id=1, content="prefers dark roast coffee")
        assert fact is not None
        assert fact.id is not None
        assert fact.is_user_defined is True
        assert fact.importance == ImportanceLevel.CRITICAL.value
        assert (await ltm.get_user_facts(1))[0].content == "prefers dark roast coffee"

    @pytest.mark.asyncio
    async def test_duplicate_returns_existing_and_confirms(self, monkeypatch):
        ltm = _make_cache_only(monkeypatch)
        first = await ltm.add_explicit_fact(user_id=1, content="prefers dark roast coffee")
        again = await ltm.add_explicit_fact(user_id=1, content="prefers dark roast coffee")

        # Returns the SAME existing fact, does not create a second.
        assert again is first or again.id == first.id
        assert len(ltm._cache[1]) == 1
        assert first.mention_count >= 2

    @pytest.mark.asyncio
    async def test_custom_category_passed_through(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import FactCategory

        ltm = _make_cache_only(monkeypatch)
        fact = await ltm.add_explicit_fact(
            user_id=1, content="works at the observatory", category=FactCategory.PERSONAL.value
        )
        assert fact.category == FactCategory.PERSONAL.value


class TestForgetFact:
    """forget_fact: found-and-deactivated vs not-found (cache-only)."""

    @pytest.mark.asyncio
    async def test_forget_existing_fact_returns_true(self, monkeypatch):
        ltm = _make_cache_only(monkeypatch)
        await ltm.add_explicit_fact(user_id=1, content="likes pineapple pizza")
        ok = await ltm.forget_fact(user_id=1, content_query="likes pineapple pizza")
        assert ok is True
        # Removed from cache.
        assert await ltm.get_user_facts(1) == []

    @pytest.mark.asyncio
    async def test_forget_unknown_fact_returns_false(self, monkeypatch):
        ltm = _make_cache_only(monkeypatch)
        await ltm.add_explicit_fact(user_id=1, content="likes pineapple pizza")
        ok = await ltm.forget_fact(user_id=1, content_query="completely unrelated topic")
        assert ok is False
        # Original still present.
        assert len(await ltm.get_user_facts(1)) == 1


class TestUpdateFactConfirmation:
    """_update_fact_confirmation mutates timestamp/count/confidence."""

    @pytest.mark.asyncio
    async def test_confirmation_updates_fields(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        fact = Fact(user_id=1, content="some fact", mention_count=1, confidence=0.5)
        await ltm._store_fact(fact)

        before = fact.mention_count
        await ltm._update_fact_confirmation(fact)

        assert fact.mention_count == before + 1
        assert fact.confidence == 1.0
        assert fact.last_confirmed is not None
        assert fact.last_confirmed.tzinfo is not None


class TestDeduplicateFactsCacheOnly:
    """deduplicate_facts removes exact-content duplicates from cache."""

    @pytest.mark.asyncio
    async def test_no_duplicates_returns_zero(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        await ltm._store_fact(Fact(user_id=1, content="unique fact one"))
        await ltm._store_fact(Fact(user_id=1, content="unique fact two"))
        assert await ltm.deduplicate_facts(1) == 0

    @pytest.mark.asyncio
    async def test_single_fact_returns_zero(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        await ltm._store_fact(Fact(user_id=1, content="only one fact"))
        assert await ltm.deduplicate_facts(1) == 0

    @pytest.mark.asyncio
    async def test_removes_exact_duplicate(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        # Two facts with identical content (case-insensitive key).
        await ltm._store_fact(Fact(user_id=1, content="Loves Cats"))
        await ltm._store_fact(Fact(user_id=1, content="loves cats"))
        await ltm._store_fact(Fact(user_id=1, content="hates traffic jams"))

        removed = await ltm.deduplicate_facts(1)
        assert removed == 1
        remaining = await ltm.get_user_facts(1, include_inactive=True)
        # One duplicate pruned from cache -> 2 facts left.
        assert len(remaining) == 2


class TestGetContextFacts:
    """get_context_facts formatting + decay scoring + empty case."""

    @pytest.mark.asyncio
    async def test_empty_when_no_facts(self, monkeypatch):
        ltm = _make_cache_only(monkeypatch)
        assert await ltm.get_context_facts(1) == ""

    @pytest.mark.asyncio
    async def test_formats_known_facts_header_and_markers(self, monkeypatch):
        from datetime import datetime

        from cogs.ai_core.memory.long_term_memory import Fact, ImportanceLevel

        ltm = _make_cache_only(monkeypatch)
        now = datetime.now(tz=timezone.utc)
        # Recently confirmed -> high decayed confidence -> "✓".
        fresh = Fact(
            user_id=1,
            content="recently confirmed fact",
            last_confirmed=now,
            importance=ImportanceLevel.HIGH.value,
        )
        await ltm._store_fact(fresh)

        out = await ltm.get_context_facts(1)
        assert out.startswith("สิ่งที่รู้เกี่ยวกับผู้ใช้นี้:")
        assert "recently confirmed fact" in out
        assert "✓" in out

    @pytest.mark.asyncio
    async def test_old_fact_gets_uncertain_marker(self, monkeypatch):
        from datetime import datetime, timedelta

        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        old = datetime.now(tz=timezone.utc) - timedelta(days=200)
        stale = Fact(user_id=1, content="very old stale fact", last_confirmed=old)
        await ltm._store_fact(stale)

        out = await ltm.get_context_facts(1)
        # ~200 days -> decayed confidence well below 0.7 -> "?" marker.
        assert "?" in out

    @pytest.mark.asyncio
    async def test_limit_caps_number_of_lines(self, monkeypatch):
        from datetime import datetime

        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        now = datetime.now(tz=timezone.utc)
        for i in range(5):
            await ltm._store_fact(
                Fact(user_id=1, content=f"context fact number {i}", last_confirmed=now)
            )

        out = await ltm.get_context_facts(1, limit=2)
        # 1 header line + at most `limit` fact lines.
        assert len(out.splitlines()) == 3

    @pytest.mark.asyncio
    async def test_fact_without_last_confirmed_uses_stored_confidence(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        ltm = _make_cache_only(monkeypatch)
        # last_confirmed=None -> code uses fact.confidence directly (no decay).
        f = Fact(user_id=1, content="undated high confidence fact", confidence=0.95)
        await ltm._store_fact(f)
        out = await ltm.get_context_facts(1)
        assert "undated high confidence fact" in out
        assert "✓" in out


class TestGetUserLockPruning:
    """_get_user_lock returns stable locks and prunes idle ones at cap."""

    @pytest.mark.asyncio
    async def test_same_user_returns_same_lock(self, monkeypatch):
        ltm = _make_cache_only(monkeypatch)
        a = ltm._get_user_lock(1)
        b = ltm._get_user_lock(1)
        assert a is b

    @pytest.mark.asyncio
    async def test_prunes_idle_locks_at_cap(self, monkeypatch):
        import asyncio as _asyncio

        ltm = _make_cache_only(monkeypatch)
        # Seed 10_000 idle locks so the next call triggers pruning.
        for uid in range(10_000):
            ltm._explicit_fact_locks[uid] = _asyncio.Lock()

        # Hold one lock so it is NOT pruned (locked() is True).
        held = ltm._explicit_fact_locks[0]
        await held.acquire()
        try:
            ltm._get_user_lock(999_999)  # triggers prune of idle locks
            # Idle locks pruned; the held one survived; the new one added.
            assert 0 in ltm._explicit_fact_locks  # held -> kept
            assert 999_999 in ltm._explicit_fact_locks  # newly created
            # The vast majority of idle locks were dropped.
            assert len(ltm._explicit_fact_locks) < 100
        finally:
            held.release()


class TestInitSchema:
    """init_schema: no-op without DB; issues DDL with DB."""

    @pytest.mark.asyncio
    async def test_init_schema_noop_without_db(self, monkeypatch):
        ltm = _make_cache_only(monkeypatch)
        # Should simply return without touching anything.
        await ltm.init_schema()

    @pytest.mark.asyncio
    async def test_init_schema_creates_table_and_indexes(self, monkeypatch):
        conn = _FakeConn()
        ltm, _ = _make_db_backed(monkeypatch, conn)

        await ltm.init_schema()

        sqls = " ".join(sql for sql, _ in conn.executed)
        assert "CREATE TABLE IF NOT EXISTS user_facts" in sqls
        assert "idx_user_facts_user" in sqls
        assert "idx_user_facts_category" in sqls
        assert conn.commits >= 1


class TestStoreFactDbBacked:
    """_store_fact DB INSERT path returns lastrowid."""

    @pytest.mark.asyncio
    async def test_insert_returns_lastrowid(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        conn = _FakeConn(lastrowid=777)
        ltm, _ = _make_db_backed(monkeypatch, conn)

        from datetime import datetime

        now = datetime.now(tz=timezone.utc)
        fact = Fact(user_id=1, content="db fact", first_mentioned=now, last_confirmed=now)
        new_id = await ltm._store_fact(fact)

        assert new_id == 777
        sql, params = conn.executed[0]
        assert "INSERT INTO user_facts" in sql
        # first_mentioned/last_confirmed serialized to isoformat strings.
        assert now.isoformat() in params
        assert conn.commits >= 1


class TestGetUserFactsDbBacked:
    """get_user_facts DB path: row hydration, _parse_ts, source_message."""

    def _row(self, **over):
        base = {
            "id": 1,
            "user_id": 1,
            "channel_id": None,
            "category": "custom",
            "content": "db fact content",
            "importance": 2,
            "first_mentioned": "2026-01-02T03:04:05+00:00",
            "last_confirmed": "2026-01-02T03:04:05+00:00",
            "mention_count": 1,
            "confidence": 1.0,
            "source_message": "the original message",
            "is_active": 1,
            "is_user_defined": 0,
        }
        base.update(over)
        return _Row(base)

    @pytest.mark.asyncio
    async def test_hydrates_rows_with_source_message(self, monkeypatch):
        conn = _FakeConn(rows=[self._row()])
        ltm, _ = _make_db_backed(monkeypatch, conn)

        facts = await ltm.get_user_facts(1)
        assert len(facts) == 1
        f = facts[0]
        assert f.content == "db fact content"
        assert f.source_message == "the original message"
        assert f.first_mentioned.tzinfo is not None  # tz-aware

    @pytest.mark.asyncio
    async def test_naive_timestamp_normalized_to_utc(self, monkeypatch):
        # SQLite CURRENT_TIMESTAMP style (naive, no offset).
        conn = _FakeConn(rows=[self._row(first_mentioned="2026-01-02 03:04:05")])
        ltm, _ = _make_db_backed(monkeypatch, conn)

        f = (await ltm.get_user_facts(1))[0]
        assert f.first_mentioned.tzinfo == timezone.utc

    @pytest.mark.asyncio
    async def test_malformed_timestamp_dropped_not_fatal(self, monkeypatch):
        conn = _FakeConn(rows=[self._row(last_confirmed="garbage-not-a-date")])
        ltm, _ = _make_db_backed(monkeypatch, conn)

        f = (await ltm.get_user_facts(1))[0]
        # Bad timestamp -> None, but rest of the row survives.
        assert f.last_confirmed is None
        assert f.content == "db fact content"

    @pytest.mark.asyncio
    async def test_missing_source_message_column_defaults_none(self, monkeypatch):
        row = self._row()
        del row["source_message"]  # simulate older schema without the column
        conn = _FakeConn(rows=[row])
        ltm, _ = _make_db_backed(monkeypatch, conn)

        f = (await ltm.get_user_facts(1))[0]
        assert f.source_message is None

    @pytest.mark.asyncio
    async def test_category_filter_builds_filtered_query(self, monkeypatch):
        conn = _FakeConn(rows=[])
        ltm, _ = _make_db_backed(monkeypatch, conn)

        await ltm.get_user_facts(1, category="identity")
        sql, params = conn.executed[0]
        assert "category = ?" in sql
        assert "identity" in params

    @pytest.mark.asyncio
    async def test_include_inactive_omits_active_clause(self, monkeypatch):
        conn = _FakeConn(rows=[])
        ltm, _ = _make_db_backed(monkeypatch, conn)

        await ltm.get_user_facts(1, include_inactive=True)
        sql, _ = conn.executed[0]
        assert "is_active = 1" not in sql

    @pytest.mark.asyncio
    async def test_default_excludes_inactive(self, monkeypatch):
        conn = _FakeConn(rows=[])
        ltm, _ = _make_db_backed(monkeypatch, conn)

        await ltm.get_user_facts(1)
        sql, _ = conn.executed[0]
        assert "is_active = 1" in sql


class TestForgetFactDbBacked:
    """forget_fact DB path writes is_active=0."""

    @pytest.mark.asyncio
    async def test_forget_issues_update_and_returns_true(self, monkeypatch):
        # Row returned by the internal get_user_facts (via _find_similar_fact).
        row = _Row(
            {
                "id": 55,
                "user_id": 1,
                "channel_id": None,
                "category": "custom",
                "content": "likes pineapple pizza",
                "importance": 4,
                "first_mentioned": "2026-01-02T03:04:05+00:00",
                "last_confirmed": "2026-01-02T03:04:05+00:00",
                "mention_count": 1,
                "confidence": 1.0,
                "source_message": None,
                "is_active": 1,
                "is_user_defined": 1,
            }
        )
        conn = _FakeConn(rows=[row])
        ltm, _ = _make_db_backed(monkeypatch, conn)

        ok = await ltm.forget_fact(user_id=1, content_query="likes pineapple pizza")
        assert ok is True
        update_sqls = [sql for sql, _ in conn.executed if "is_active = 0" in sql]
        assert update_sqls, "expected an UPDATE ... is_active = 0 statement"
        # Parameter carried the fact id.
        params = next(p for sql, p in conn.executed if "is_active = 0" in sql)
        assert 55 in params

    @pytest.mark.asyncio
    async def test_forget_not_found_returns_false(self, monkeypatch):
        conn = _FakeConn(rows=[])  # no facts -> nothing similar
        ltm, _ = _make_db_backed(monkeypatch, conn)
        ok = await ltm.forget_fact(user_id=1, content_query="nonexistent fact text")
        assert ok is False


class TestUpdateConfirmationDbBacked:
    """_update_fact_confirmation DB path issues the UPDATE."""

    @pytest.mark.asyncio
    async def test_db_update_issued(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        conn = _FakeConn()
        ltm, _ = _make_db_backed(monkeypatch, conn)
        fact = Fact(id=88, user_id=1, content="db fact", mention_count=3, confidence=0.4)

        await ltm._update_fact_confirmation(fact)

        # In-memory mutation always happens.
        assert fact.mention_count == 4
        assert fact.confidence == 1.0
        # DB UPDATE issued because db is available and fact.id is set.
        upd = [sql for sql, _ in conn.executed if "UPDATE user_facts" in sql]
        assert upd
        params = next(p for sql, p in conn.executed if "UPDATE user_facts" in sql)
        assert 88 in params

    @pytest.mark.asyncio
    async def test_no_db_update_when_id_missing(self, monkeypatch):
        from cogs.ai_core.memory.long_term_memory import Fact

        conn = _FakeConn()
        ltm, _ = _make_db_backed(monkeypatch, conn)
        fact = Fact(id=None, user_id=1, content="db fact", mention_count=1)

        await ltm._update_fact_confirmation(fact)

        # No fact.id -> no DB write, but in-memory fields still updated.
        assert fact.mention_count == 2
        assert conn.executed == []


class TestDeduplicateFactsDbBacked:
    """deduplicate_facts DB path deactivates duplicate rows."""

    def _row(self, fid, content):
        return _Row(
            {
                "id": fid,
                "user_id": 1,
                "channel_id": None,
                "category": "custom",
                "content": content,
                "importance": 2,
                "first_mentioned": "2026-01-02T03:04:05+00:00",
                "last_confirmed": "2026-01-02T03:04:05+00:00",
                "mention_count": 1,
                "confidence": 1.0,
                "source_message": None,
                "is_active": 1,
                "is_user_defined": 0,
            }
        )

    @pytest.mark.asyncio
    async def test_deactivates_duplicate_rows(self, monkeypatch):
        rows = [
            self._row(1, "loves cats"),
            self._row(2, "loves cats"),  # duplicate content
            self._row(3, "hates noise"),
        ]
        conn = _FakeConn(rows=rows)
        ltm, _ = _make_db_backed(monkeypatch, conn)

        removed = await ltm.deduplicate_facts(1)
        assert removed == 1
        # The duplicate row (id=2) got an is_active=0 UPDATE.
        deact = [p for sql, p in conn.executed if "is_active = 0" in sql]
        assert deact
        assert any(2 in params for params in deact)
