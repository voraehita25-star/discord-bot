"""
Tests for cogs.ai_core.memory.entity_memory module.
"""

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
            appearance="Tall with dark hair",
        )

        assert facts.age == 25
        assert facts.occupation == "Student"
        assert facts.personality == "Friendly"

    def test_entity_facts_with_relationships(self):
        """Test EntityFacts with relationships."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(relationships={"Alice": "friend", "Bob": "sibling"})

        assert facts.relationships["Alice"] == "friend"
        assert facts.relationships["Bob"] == "sibling"

    def test_entity_facts_to_dict(self):
        """Test EntityFacts to_dict method."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(description="Test description", age=30, occupation="Teacher")

        result = facts.to_dict()

        assert result["description"] == "Test description"
        assert result["age"] == 30
        # None values should be excluded
        assert "personality" not in result or result.get("personality") is None

    def test_entity_facts_from_dict(self):
        """Test EntityFacts from_dict method."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        data = {"description": "Test entity", "age": 25, "occupation": "Engineer"}

        facts = EntityFacts.from_dict(data)

        assert facts.description == "Test entity"
        assert facts.age == 25
        assert facts.occupation == "Engineer"

    def test_entity_facts_from_dict_with_custom_fields(self):
        """Test EntityFacts from_dict with custom fields."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        data = {"description": "Test", "custom_field": "custom_value"}

        facts = EntityFacts.from_dict(data)

        assert facts.description == "Test"
        assert facts.custom.get("custom_field") == "custom_value"

    def test_entity_facts_to_prompt_text(self):
        """Test EntityFacts to_prompt_text method."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(description="A mysterious person", age=30, occupation="Detective")

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
        entity = Entity(entity_id=1, name="Faust", entity_type="character", facts=facts)

        assert entity.name == "Faust"
        assert entity.entity_type == "character"
        assert entity.confidence == 1.0

    def test_entity_to_prompt_text(self):
        """Test Entity to_prompt_text method."""
        from cogs.ai_core.memory.entity_memory import Entity, EntityFacts

        facts = EntityFacts(description="A wise person")
        entity = Entity(entity_id=1, name="Sage", entity_type="character", facts=facts)

        result = entity.to_prompt_text()

        assert "CHARACTER" in result
        assert "Sage" in result
        assert "wise person" in result

    def test_entity_default_values(self):
        """Test Entity default values."""
        from cogs.ai_core.memory.entity_memory import Entity, EntityFacts

        facts = EntityFacts()
        entity = Entity(entity_id=1, name="Test", entity_type="item", facts=facts)

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

    def test_global_instance_is_manager(self):
        """Test global entity_memory is EntityMemoryManager."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager, entity_memory

        assert isinstance(entity_memory, EntityMemoryManager)


class TestEntityFactsLocationFields:
    """Tests for EntityFacts location-specific fields."""

    def test_location_fields(self):
        """Test location-specific fields."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(location_type="apartment", address="123 Main Street")

        assert facts.location_type == "apartment"
        assert facts.address == "123 Main Street"

    def test_location_to_prompt_text(self):
        """Test location fields in prompt text."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(location_type="cafe", address="Downtown Area")

        result = facts.to_prompt_text()

        assert "cafe" in result
        assert "Downtown Area" in result


class TestEntityFactsItemFields:
    """Tests for EntityFacts item-specific fields."""

    def test_item_fields(self):
        """Test item-specific fields."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(owner="Alice", item_type="weapon")

        assert facts.owner == "Alice"
        assert facts.item_type == "weapon"


class TestEntityFactsCustomFields:
    """Tests for EntityFacts custom fields."""

    def test_custom_fields(self):
        """Test custom fields dictionary."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(custom={"special_ability": "teleport", "power_level": 9000})

        assert facts.custom["special_ability"] == "teleport"
        assert facts.custom["power_level"] == 9000

    def test_custom_fields_in_prompt(self):
        """Test custom fields appear in prompt text."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(custom={"special_ability": "teleportation"})

        result = facts.to_prompt_text()

        assert "special_ability" in result
        assert "teleportation" in result


class TestEntityFactsAgePromptText:
    """Regression tests for age handling in EntityFacts.to_prompt_text.

    The age line used a falsy check (`if self.age:`) which silently dropped
    age 0 (a newborn / "age zero" character). It was fixed to
    `if self.age is not None:` so age 0 is now rendered.
    """

    def test_age_zero_is_included(self):
        """Regression: age == 0 must appear in the prompt text (was dropped)."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(description="A newborn character", age=0)

        result = facts.to_prompt_text()

        # The Thai "อายุ" (age) label line must be present and contain "0".
        assert "อายุ" in result
        assert "0" in result
        # Specifically the rendered age line.
        assert any(line.startswith("อายุ") and "0" in line for line in result.split("\n"))

    def test_age_none_is_omitted(self):
        """age is None: no age line should be rendered."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(description="No age given", age=None)

        result = facts.to_prompt_text()

        assert "อายุ" not in result
        # description still rendered, just no age.
        assert "No age given" in result

    def test_positive_age_is_included(self):
        """A normal positive age still appears."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(age=42)

        result = facts.to_prompt_text()

        assert "อายุ" in result
        assert "42" in result

    def test_age_zero_survives_entity_prompt_text(self):
        """End-to-end via Entity.to_prompt_text: age 0 reaches the scrubbed output."""
        from cogs.ai_core.memory.entity_memory import Entity, EntityFacts

        facts = EntityFacts(description="baby", age=0)
        entity = Entity(entity_id=1, name="Zero", entity_type="character", facts=facts)

        result = entity.to_prompt_text()

        assert "CHARACTER" in result
        assert "Zero" in result
        assert "อายุ" in result
        assert "0" in result

    def test_age_zero_round_trips_through_dict(self):
        """age 0 is preserved through to_dict/from_dict and still renders.

        to_dict() must keep age 0 (it skips only None and empty containers),
        so a serialized-then-restored EntityFacts still shows the age line.
        """
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(age=0)

        as_dict = facts.to_dict()
        assert as_dict.get("age") == 0  # 0 not dropped by to_dict

        restored = EntityFacts.from_dict(as_dict)
        assert restored.age == 0

        result = restored.to_prompt_text()
        assert "อายุ" in result
        assert "0" in result


# ==================================================================
# Appended tests: deepen coverage of EntityMemoryManager DB methods,
# _row_to_entity, get_entities_for_prompt, and error/edge branches.
# ==================================================================


class _FakeCursor:
    """Stands in for an aiosqlite cursor."""

    def __init__(self, fetchone_result=None, fetchall_result=None, lastrowid=None):
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result if fetchall_result is not None else []
        self.lastrowid = lastrowid

    async def fetchone(self):
        return self._fetchone_result

    async def fetchall(self):
        return self._fetchall_result


class _FakeConn:
    """Stands in for an aiosqlite connection.

    Records every executed SQL string in ``executed`` and yields scripted
    cursors per-execute. ``in_transaction`` is configurable to drive the
    BEGIN-IMMEDIATE join-existing-tx branch in add_entity.
    """

    def __init__(self, cursors=None, in_transaction=False):
        # cursors: list of _FakeCursor returned in order per execute() call.
        self._cursors = list(cursors) if cursors is not None else []
        self._cursor_idx = 0
        self.executed = []
        self.committed = 0
        self.rolled_back = 0
        self.in_transaction = in_transaction
        self.execute_error = None  # if set, execute() raises it
        self.commit_error = None  # if set, commit() raises it

    async def execute(self, sql, params=None):
        self.executed.append((sql, params))
        if self.execute_error is not None:
            raise self.execute_error
        if self._cursor_idx < len(self._cursors):
            cur = self._cursors[self._cursor_idx]
            self._cursor_idx += 1
            return cur
        return _FakeCursor()

    async def commit(self):
        self.committed += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self):
        self.rolled_back += 1


class _FakeCtx:
    """Async context manager yielding a fixed connection."""

    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakeDBManager:
    """Mimics the subset of the DB singleton entity_memory uses."""

    def __init__(self, write_conn=None, read_conn=None):
        self._write_conn = write_conn
        self._read_conn = read_conn
        self.write_calls = 0
        self.read_calls = 0

    def get_write_connection(self):
        self.write_calls += 1
        return _FakeCtx(self._write_conn)

    def get_connection(self):
        self.read_calls += 1
        return _FakeCtx(self._read_conn)


class _FakeRow:
    """Mimics aiosqlite.Row: supports BOTH keyed (row["id"]) and positional
    (row[0]) access, in the entity_memories column order."""

    _COLUMNS = (
        "id",
        "name",
        "entity_type",
        "facts",
        "channel_id",
        "guild_id",
        "confidence",
        "source",
        "created_at",
        "updated_at",
        "access_count",
    )

    def __init__(self, values: dict):
        self._d = values

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._d[self._COLUMNS[key]]
        return self._d[key]


def _make_row(
    *,
    entity_id=1,
    name="Faust",
    entity_type="character",
    facts='{"description": "the warden"}',
    channel_id=None,
    guild_id=None,
    confidence=1.0,
    source="user",
    created_at=1000.0,
    updated_at=2000.0,
    access_count=3,
):
    """Build an aiosqlite.Row-like row (keyed AND positional access)."""
    return _FakeRow(
        {
            "id": entity_id,
            "name": name,
            "entity_type": entity_type,
            "facts": facts,
            "channel_id": channel_id,
            "guild_id": guild_id,
            "confidence": confidence,
            "source": source,
            "created_at": created_at,
            "updated_at": updated_at,
            "access_count": access_count,
        }
    )


def _em_module():
    """Return the real entity_memory MODULE object.

    NB: the parent package re-exports the ``entity_memory`` global instance,
    which shadows the submodule under attribute access (``import ... as em``
    yields the instance). Pull the genuine module out of sys.modules.
    """
    import sys

    from cogs.ai_core.memory.entity_memory import EntityFacts  # ensure import

    assert EntityFacts is not None
    return sys.modules["cogs.ai_core.memory.entity_memory"]


def _patch_db(monkeypatch, fake_dbm):
    """Patch the module-level db_manager to our fake."""
    monkeypatch.setattr(_em_module(), "db_manager", fake_dbm, raising=False)


def _new_initialized_manager():
    """A manager pre-marked initialized so initialize() short-circuits True."""
    from cogs.ai_core.memory.entity_memory import EntityMemoryManager

    mgr = EntityMemoryManager()
    mgr._initialized = True
    return mgr


class TestInitialize:
    """Cover initialize() branches beyond the already-initialized short circuit."""

    @pytest.mark.asyncio
    async def test_initialize_no_db_manager_returns_false(self, monkeypatch):
        """When db_manager is None, initialize returns the (False) flag."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        _patch_db(monkeypatch, None)
        mgr = EntityMemoryManager()

        result = await mgr.initialize()

        assert result is False
        assert mgr._initialized is False

    @pytest.mark.asyncio
    async def test_initialize_success_creates_table_and_indexes(self, monkeypatch):
        """Happy path: DDL + indexes executed and committed, flag set True."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        conn = _FakeConn()
        _patch_db(monkeypatch, _FakeDBManager(write_conn=conn))
        mgr = EntityMemoryManager()

        result = await mgr.initialize()

        assert result is True
        assert mgr._initialized is True
        # CREATE TABLE + several CREATE INDEX statements were executed.
        executed_sql = [sql for sql, _ in conn.executed]
        assert any("CREATE TABLE" in s for s in executed_sql)
        assert any("idx_entity_name" in s for s in executed_sql)
        assert conn.committed == 1

    @pytest.mark.asyncio
    async def test_initialize_db_error_returns_false(self, monkeypatch):
        """A DDL aiosqlite.Error is caught and initialize returns False."""
        import aiosqlite

        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        conn = _FakeConn()
        conn.execute_error = aiosqlite.OperationalError("disk I/O error")
        _patch_db(monkeypatch, _FakeDBManager(write_conn=conn))
        mgr = EntityMemoryManager()

        result = await mgr.initialize()

        assert result is False
        assert mgr._initialized is False


class TestAddEntity:
    """Cover add_entity insert/update/transaction/error branches."""

    @pytest.mark.asyncio
    async def test_add_entity_init_fails_returns_none(self, monkeypatch):
        """If initialize() can't run (db_manager None), add returns None."""
        from cogs.ai_core.memory.entity_memory import EntityFacts, EntityMemoryManager

        _patch_db(monkeypatch, None)
        mgr = EntityMemoryManager()  # not initialized; initialize() returns False

        result = await mgr.add_entity("Faust", "character", EntityFacts(description="x"))

        assert result is None

    @pytest.mark.asyncio
    async def test_add_entity_insert_new(self, monkeypatch):
        """New entity (no existing row) -> INSERT, returns lastrowid."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        # First execute is BEGIN IMMEDIATE (cursor unused), second is the
        # SELECT existence check (returns None), third is the INSERT.
        begin_cur = _FakeCursor()
        select_cur = _FakeCursor(fetchone_result=None)
        insert_cur = _FakeCursor(lastrowid=42)
        conn = _FakeConn(cursors=[begin_cur, select_cur, insert_cur], in_transaction=False)
        _patch_db(monkeypatch, _FakeDBManager(write_conn=conn))
        mgr = _new_initialized_manager()

        result = await mgr.add_entity("Faust", "character", EntityFacts(description="warden"))

        assert result == 42
        executed = [sql for sql, _ in conn.executed]
        assert any("BEGIN IMMEDIATE" in s for s in executed)
        assert any("INSERT INTO entity_memories" in s for s in executed)
        assert conn.committed == 1

    @pytest.mark.asyncio
    async def test_add_entity_update_existing(self, monkeypatch):
        """Existing row -> UPDATE path, returns the existing id (no INSERT)."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        begin_cur = _FakeCursor()
        select_cur = _FakeCursor(fetchone_result=(7,))  # existing id=7
        update_cur = _FakeCursor()
        conn = _FakeConn(cursors=[begin_cur, select_cur, update_cur], in_transaction=False)
        _patch_db(monkeypatch, _FakeDBManager(write_conn=conn))
        mgr = _new_initialized_manager()

        result = await mgr.add_entity("Faust", "character", EntityFacts(description="updated"))

        assert result == 7
        executed = [sql for sql, _ in conn.executed]
        assert any("UPDATE entity_memories" in s for s in executed)
        assert not any("INSERT INTO entity_memories" in s for s in executed)

    @pytest.mark.asyncio
    async def test_add_entity_joins_existing_transaction(self, monkeypatch):
        """When a tx is already open, BEGIN IMMEDIATE is skipped (join path)."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        # in_transaction True -> no BEGIN IMMEDIATE issued.
        select_cur = _FakeCursor(fetchone_result=None)
        insert_cur = _FakeCursor(lastrowid=99)
        conn = _FakeConn(cursors=[select_cur, insert_cur], in_transaction=True)
        _patch_db(monkeypatch, _FakeDBManager(write_conn=conn))
        mgr = _new_initialized_manager()

        result = await mgr.add_entity("X", "item", EntityFacts())

        assert result == 99
        executed = [sql for sql, _ in conn.executed]
        assert not any("BEGIN IMMEDIATE" in s for s in executed)

    @pytest.mark.asyncio
    async def test_add_entity_channel_only_existence_check(self, monkeypatch):
        """guild_id None, channel_id set -> uses the channel/guild-IS-NULL SELECT."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        select_cur = _FakeCursor(fetchone_result=None)
        insert_cur = _FakeCursor(lastrowid=1)
        conn = _FakeConn(cursors=[_FakeCursor(), select_cur, insert_cur], in_transaction=False)
        _patch_db(monkeypatch, _FakeDBManager(write_conn=conn))
        mgr = _new_initialized_manager()

        await mgr.add_entity("Y", "location", EntityFacts(), channel_id=55, guild_id=None)

        # The SELECT for channel-set/guild-null must reference channel_id = ? and guild_id IS NULL
        select_sqls = [sql for sql, _ in conn.executed if sql.strip().startswith("SELECT")]
        assert any("channel_id = ?" in s and "guild_id IS NULL" in s for s in select_sqls)

    @pytest.mark.asyncio
    async def test_add_entity_guild_only_existence_check(self, monkeypatch):
        """channel_id None, guild_id set -> uses channel-IS-NULL/guild SELECT."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        select_cur = _FakeCursor(fetchone_result=None)
        insert_cur = _FakeCursor(lastrowid=1)
        conn = _FakeConn(cursors=[_FakeCursor(), select_cur, insert_cur], in_transaction=False)
        _patch_db(monkeypatch, _FakeDBManager(write_conn=conn))
        mgr = _new_initialized_manager()

        await mgr.add_entity("Z", "location", EntityFacts(), channel_id=None, guild_id=77)

        select_sqls = [sql for sql, _ in conn.executed if sql.strip().startswith("SELECT")]
        assert any("channel_id IS NULL" in s and "guild_id = ?" in s for s in select_sqls)

    @pytest.mark.asyncio
    async def test_add_entity_both_set_existence_check(self, monkeypatch):
        """channel_id and guild_id both set -> exact-match SELECT."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        select_cur = _FakeCursor(fetchone_result=None)
        insert_cur = _FakeCursor(lastrowid=1)
        conn = _FakeConn(cursors=[_FakeCursor(), select_cur, insert_cur], in_transaction=False)
        _patch_db(monkeypatch, _FakeDBManager(write_conn=conn))
        mgr = _new_initialized_manager()

        await mgr.add_entity("W", "item", EntityFacts(), channel_id=1, guild_id=2)

        select_sqls = [sql for sql, _ in conn.executed if sql.strip().startswith("SELECT")]
        assert any("channel_id = ?" in s and "guild_id = ?" in s for s in select_sqls)

    @pytest.mark.asyncio
    async def test_add_entity_inner_error_rolls_back_own_tx(self, monkeypatch):
        """An aiosqlite.Error during INSERT rolls back OUR tx and returns None."""
        import aiosqlite

        from cogs.ai_core.memory.entity_memory import EntityFacts

        select_cur = _FakeCursor(fetchone_result=None)

        # Fail on the INSERT (3rd execute). Use a conn whose execute raises
        # only after the SELECT has happened.
        class _ConnFailOnInsert(_FakeConn):
            async def execute(self, sql, params=None):
                self.executed.append((sql, params))
                if "INSERT INTO entity_memories" in sql:
                    raise aiosqlite.OperationalError("constraint failed")
                if self._cursor_idx < len(self._cursors):
                    cur = self._cursors[self._cursor_idx]
                    self._cursor_idx += 1
                    return cur
                return _FakeCursor()

        conn = _ConnFailOnInsert(cursors=[_FakeCursor(), select_cur], in_transaction=False)
        _patch_db(monkeypatch, _FakeDBManager(write_conn=conn))
        mgr = _new_initialized_manager()

        result = await mgr.add_entity("Boom", "character", EntityFacts())

        assert result is None
        # We began the tx (own_tx) so rollback should have fired.
        assert conn.rolled_back == 1

    @pytest.mark.asyncio
    async def test_add_entity_joined_tx_error_does_not_rollback(self, monkeypatch):
        """When we JOINED an existing tx, an error must NOT trigger our rollback."""
        import aiosqlite

        from cogs.ai_core.memory.entity_memory import EntityFacts

        select_cur = _FakeCursor(fetchone_result=None)

        class _ConnFailOnInsert(_FakeConn):
            async def execute(self, sql, params=None):
                self.executed.append((sql, params))
                if "INSERT INTO entity_memories" in sql:
                    raise aiosqlite.OperationalError("constraint failed")
                if self._cursor_idx < len(self._cursors):
                    cur = self._cursors[self._cursor_idx]
                    self._cursor_idx += 1
                    return cur
                return _FakeCursor()

        # in_transaction True => _own_tx False => no rollback on error.
        conn = _ConnFailOnInsert(cursors=[select_cur], in_transaction=True)
        _patch_db(monkeypatch, _FakeDBManager(write_conn=conn))
        mgr = _new_initialized_manager()

        result = await mgr.add_entity("Boom", "character", EntityFacts())

        assert result is None
        assert conn.rolled_back == 0


class TestGetEntity:
    """Cover get_entity read-only path, write path, no-row, and error paths."""

    @pytest.mark.asyncio
    async def test_get_entity_init_fails_returns_none(self, monkeypatch):
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        _patch_db(monkeypatch, None)
        mgr = EntityMemoryManager()

        assert await mgr.get_entity("Faust") is None

    @pytest.mark.asyncio
    async def test_get_entity_read_only_returns_entity(self, monkeypatch):
        """update_access=False uses the read pool (no write/commit)."""
        row = _make_row(name="Ember", entity_type="character")
        read_conn = _FakeConn(cursors=[_FakeCursor(fetchone_result=row)])
        dbm = _FakeDBManager(read_conn=read_conn)
        _patch_db(monkeypatch, dbm)
        mgr = _new_initialized_manager()

        entity = await mgr.get_entity("Ember", update_access=False)

        assert entity is not None
        assert entity.name == "Ember"
        assert dbm.read_calls == 1
        assert dbm.write_calls == 0
        assert read_conn.committed == 0

    @pytest.mark.asyncio
    async def test_get_entity_read_only_no_row_returns_none(self, monkeypatch):
        read_conn = _FakeConn(cursors=[_FakeCursor(fetchone_result=None)])
        _patch_db(monkeypatch, _FakeDBManager(read_conn=read_conn))
        mgr = _new_initialized_manager()

        assert await mgr.get_entity("Missing", update_access=False) is None

    @pytest.mark.asyncio
    async def test_get_entity_with_access_bump(self, monkeypatch):
        """update_access=True uses the write connection, bumps access_count, commits."""
        row = _make_row(entity_id=5, name="Echo")
        write_conn = _FakeConn(cursors=[_FakeCursor(fetchone_result=row), _FakeCursor()])
        dbm = _FakeDBManager(write_conn=write_conn)
        _patch_db(monkeypatch, dbm)
        mgr = _new_initialized_manager()

        entity = await mgr.get_entity("Echo", update_access=True)

        assert entity is not None
        assert entity.name == "Echo"
        assert dbm.write_calls == 1
        # The UPDATE access_count statement must have run + commit.
        assert any("access_count = access_count + 1" in sql for sql, _ in write_conn.executed)
        assert write_conn.committed == 1

    @pytest.mark.asyncio
    async def test_get_entity_with_access_no_row(self, monkeypatch):
        """Write path with no matching row returns None without bumping."""
        write_conn = _FakeConn(cursors=[_FakeCursor(fetchone_result=None)])
        _patch_db(monkeypatch, _FakeDBManager(write_conn=write_conn))
        mgr = _new_initialized_manager()

        result = await mgr.get_entity("Nope", update_access=True)

        assert result is None
        assert not any("access_count = access_count + 1" in sql for sql, _ in write_conn.executed)

    @pytest.mark.asyncio
    async def test_get_entity_db_error_returns_none(self, monkeypatch):
        import aiosqlite

        write_conn = _FakeConn()
        write_conn.execute_error = aiosqlite.OperationalError("locked")
        _patch_db(monkeypatch, _FakeDBManager(write_conn=write_conn))
        mgr = _new_initialized_manager()

        assert await mgr.get_entity("Faust", update_access=True) is None


class TestSearchEntities:
    """Cover search_entities filters, escaping, and error paths."""

    @pytest.mark.asyncio
    async def test_search_init_fails_returns_empty(self, monkeypatch):
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        _patch_db(monkeypatch, None)
        mgr = EntityMemoryManager()

        assert await mgr.search_entities("q") == []

    @pytest.mark.asyncio
    async def test_search_returns_entities_with_all_filters(self, monkeypatch):
        rows = [_make_row(entity_id=1, name="A"), _make_row(entity_id=2, name="B")]
        read_conn = _FakeConn(cursors=[_FakeCursor(fetchall_result=rows)])
        _patch_db(monkeypatch, _FakeDBManager(read_conn=read_conn))
        mgr = _new_initialized_manager()

        results = await mgr.search_entities(
            "war", entity_type="character", channel_id=10, guild_id=20, limit=5
        )

        assert [e.name for e in results] == ["A", "B"]
        sql, params = read_conn.executed[0]
        assert "entity_type = ?" in sql
        assert "channel_id = ?" in sql
        assert "guild_id = ?" in sql
        assert "character" in params
        assert params[-1] == 5  # limit

    @pytest.mark.asyncio
    async def test_search_escapes_like_wildcards(self, monkeypatch):
        """LIKE-special chars in the query are escaped before binding."""
        read_conn = _FakeConn(cursors=[_FakeCursor(fetchall_result=[])])
        _patch_db(monkeypatch, _FakeDBManager(read_conn=read_conn))
        mgr = _new_initialized_manager()

        await mgr.search_entities("50%_off\\")

        _, params = read_conn.executed[0]
        # First two params are the name/facts LIKE patterns.
        assert params[0] == "%50\\%\\_off\\\\%"

    @pytest.mark.asyncio
    async def test_search_db_error_returns_empty(self, monkeypatch):
        import aiosqlite

        read_conn = _FakeConn()
        read_conn.execute_error = aiosqlite.OperationalError("boom")
        _patch_db(monkeypatch, _FakeDBManager(read_conn=read_conn))
        mgr = _new_initialized_manager()

        assert await mgr.search_entities("q") == []


class TestUpdateEntityFacts:
    """Cover update_entity_facts merge/no-merge, missing entity, and error."""

    @pytest.mark.asyncio
    async def test_update_missing_entity_returns_false(self, monkeypatch):
        """No existing entity -> returns False, never calls add_entity."""
        # get_entity (read-only) finds nothing.
        read_conn = _FakeConn(cursors=[_FakeCursor(fetchone_result=None)])
        _patch_db(monkeypatch, _FakeDBManager(read_conn=read_conn))
        mgr = _new_initialized_manager()

        result = await mgr.update_entity_facts("Ghost", {"description": "x"})

        assert result is False

    @pytest.mark.asyncio
    async def test_update_merge_combines_facts(self, monkeypatch):
        """merge=True merges new facts onto existing facts and upserts."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        existing = _make_entity_for_update(
            channel_id=None, guild_id=None, facts_dict={"description": "old", "age": 20}
        )

        captured = {}

        async def fake_get_entity(name, channel_id=None, guild_id=None, update_access=True):
            assert update_access is False  # update path must read-only
            return existing

        async def fake_add_entity(**kwargs):
            captured.update(kwargs)
            return 123

        mgr = EntityMemoryManager()
        mgr._initialized = True
        monkeypatch.setattr(mgr, "get_entity", fake_get_entity)
        monkeypatch.setattr(mgr, "add_entity", fake_add_entity)

        result = await mgr.update_entity_facts("Faust", {"occupation": "warden"})

        assert result is True
        merged = captured["facts"].to_dict()
        # old fields preserved, new field added.
        assert merged["description"] == "old"
        assert merged["age"] == 20
        assert merged["occupation"] == "warden"

    @pytest.mark.asyncio
    async def test_update_no_merge_replaces_facts(self, monkeypatch):
        """merge=False replaces facts entirely (old fields dropped)."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        existing = _make_entity_for_update(facts_dict={"description": "old", "age": 20})
        captured = {}

        async def fake_get_entity(name, channel_id=None, guild_id=None, update_access=True):
            return existing

        async def fake_add_entity(**kwargs):
            captured.update(kwargs)
            return 1

        mgr = EntityMemoryManager()
        mgr._initialized = True
        monkeypatch.setattr(mgr, "get_entity", fake_get_entity)
        monkeypatch.setattr(mgr, "add_entity", fake_add_entity)

        result = await mgr.update_entity_facts("Faust", {"occupation": "warden"}, merge=False)

        assert result is True
        replaced = captured["facts"].to_dict()
        assert replaced.get("occupation") == "warden"
        assert "description" not in replaced
        assert "age" not in replaced

    @pytest.mark.asyncio
    async def test_update_uses_loaded_entity_scope_not_caller_scope(self, monkeypatch):
        """The upsert scopes to the loaded entity's channel/guild, not caller args."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        # Loaded entity is the GLOBAL row (channel/guild None) even though the
        # caller passes a specific channel_id. add_entity must receive None.
        existing = _make_entity_for_update(channel_id=None, guild_id=None)
        captured = {}

        async def fake_get_entity(name, channel_id=None, guild_id=None, update_access=True):
            return existing

        async def fake_add_entity(**kwargs):
            captured.update(kwargs)
            return 1

        mgr = EntityMemoryManager()
        mgr._initialized = True
        monkeypatch.setattr(mgr, "get_entity", fake_get_entity)
        monkeypatch.setattr(mgr, "add_entity", fake_add_entity)

        await mgr.update_entity_facts("Faust", {"age": 30}, channel_id=999, guild_id=888)

        assert captured["channel_id"] is None
        assert captured["guild_id"] is None

    @pytest.mark.asyncio
    async def test_update_returns_false_when_add_returns_none(self, monkeypatch):
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        existing = _make_entity_for_update()

        async def fake_get_entity(name, channel_id=None, guild_id=None, update_access=True):
            return existing

        async def fake_add_entity(**kwargs):
            return None  # add failed

        mgr = EntityMemoryManager()
        mgr._initialized = True
        monkeypatch.setattr(mgr, "get_entity", fake_get_entity)
        monkeypatch.setattr(mgr, "add_entity", fake_add_entity)

        assert await mgr.update_entity_facts("Faust", {"age": 1}) is False

    @pytest.mark.asyncio
    async def test_update_value_error_during_merge_returns_false(self, monkeypatch):
        """A ValueError raised while building facts is caught -> False."""
        from cogs.ai_core.memory.entity_memory import EntityFacts, EntityMemoryManager

        existing = _make_entity_for_update()

        async def fake_get_entity(name, channel_id=None, guild_id=None, update_access=True):
            return existing

        def boom_from_dict(data):
            raise ValueError("bad facts")

        mgr = EntityMemoryManager()
        mgr._initialized = True
        monkeypatch.setattr(mgr, "get_entity", fake_get_entity)
        monkeypatch.setattr(EntityFacts, "from_dict", staticmethod(boom_from_dict))

        assert await mgr.update_entity_facts("Faust", {"age": 1}) is False


class TestGetAllEntities:
    """Cover get_all_entities filters and error paths."""

    @pytest.mark.asyncio
    async def test_get_all_init_fails_returns_empty(self, monkeypatch):
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        _patch_db(monkeypatch, None)
        mgr = EntityMemoryManager()

        assert await mgr.get_all_entities() == []

    @pytest.mark.asyncio
    async def test_get_all_db_none_after_init_returns_empty(self, monkeypatch):
        """initialize() True but db_manager None -> early empty return."""
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        _patch_db(monkeypatch, None)
        mgr = EntityMemoryManager()
        mgr._initialized = True  # initialize() short-circuits True

        assert await mgr.get_all_entities() == []

    @pytest.mark.asyncio
    async def test_get_all_with_filters(self, monkeypatch):
        rows = [_make_row(entity_id=1, name="A"), _make_row(entity_id=2, name="B")]
        read_conn = _FakeConn(cursors=[_FakeCursor(fetchall_result=rows)])
        _patch_db(monkeypatch, _FakeDBManager(read_conn=read_conn))
        mgr = _new_initialized_manager()

        results = await mgr.get_all_entities(
            entity_type="location", channel_id=3, guild_id=4, limit=50
        )

        assert [e.name for e in results] == ["A", "B"]
        sql, params = read_conn.executed[0]
        assert "entity_type = ?" in sql
        assert "channel_id = ?" in sql
        assert "guild_id = ?" in sql
        assert params[-1] == 50

    @pytest.mark.asyncio
    async def test_get_all_no_filters(self, monkeypatch):
        rows = [_make_row(entity_id=1, name="Solo")]
        read_conn = _FakeConn(cursors=[_FakeCursor(fetchall_result=rows)])
        _patch_db(monkeypatch, _FakeDBManager(read_conn=read_conn))
        mgr = _new_initialized_manager()

        results = await mgr.get_all_entities()

        assert [e.name for e in results] == ["Solo"]
        sql, _ = read_conn.executed[0]
        assert "WHERE 1=1" in sql

    @pytest.mark.asyncio
    async def test_get_all_db_error_returns_empty(self, monkeypatch):
        import aiosqlite

        read_conn = _FakeConn()
        read_conn.execute_error = aiosqlite.OperationalError("nope")
        _patch_db(monkeypatch, _FakeDBManager(read_conn=read_conn))
        mgr = _new_initialized_manager()

        assert await mgr.get_all_entities() == []


class TestRowToEntity:
    """Cover _row_to_entity keyed access, positional fallback, corrupted JSON."""

    def test_row_to_entity_keyed_access(self):
        mgr = _new_initialized_manager()
        row = _make_row(
            entity_id=9,
            name="Keyed",
            entity_type="character",
            facts='{"description": "kd", "age": 33}',
            channel_id=5,
            guild_id=6,
            confidence=0.8,
            source="ai_extracted",
            access_count=4,
        )

        entity = mgr._row_to_entity(row)

        assert entity.entity_id == 9
        assert entity.name == "Keyed"
        assert entity.facts.description == "kd"
        assert entity.facts.age == 33
        assert entity.channel_id == 5
        assert entity.confidence == 0.8
        assert entity.source == "ai_extracted"
        assert entity.access_count == 4

    def test_row_to_entity_positional_fallback(self):
        """A plain tuple row (no keyed access) hits the positional fallback."""
        mgr = _new_initialized_manager()
        # Order matches the except-branch positional indices.
        row = (
            11,  # id
            "Tuple",  # name
            "item",  # entity_type
            '{"description": "td"}',  # facts
            None,  # channel_id
            None,  # guild_id
            0.5,  # confidence
            "manual",  # source
            100.0,  # created_at
            200.0,  # updated_at
            7,  # access_count
        )

        entity = mgr._row_to_entity(row)

        assert entity.entity_id == 11
        assert entity.name == "Tuple"
        assert entity.entity_type == "item"
        assert entity.facts.description == "td"
        assert entity.source == "manual"
        assert entity.access_count == 7

    def test_row_to_entity_corrupted_json_falls_back_empty(self):
        """Invalid JSON in facts -> empty EntityFacts, no exception."""
        mgr = _new_initialized_manager()
        row = _make_row(facts="{not valid json")

        entity = mgr._row_to_entity(row)

        # Empty facts -> all default Nones.
        assert entity.facts.description is None
        assert entity.facts.to_dict() == {}

    def test_row_to_entity_null_confidence_defaults_to_one(self):
        """NULL confidence/source/access_count coalesce to defaults."""
        mgr = _new_initialized_manager()
        row = _make_row(confidence=None, source=None, access_count=None)

        entity = mgr._row_to_entity(row)

        assert entity.confidence == 1.0
        assert entity.source == "user"
        assert entity.access_count == 0

    def test_row_to_entity_empty_facts_string(self):
        """Empty/falsy facts string -> empty facts dict (no JSON parse)."""
        mgr = _new_initialized_manager()
        row = _make_row(facts="")

        entity = mgr._row_to_entity(row)

        assert entity.facts.to_dict() == {}


class TestGetEntitiesForPrompt:
    """Cover get_entities_for_prompt aggregation and empty result."""

    @pytest.mark.asyncio
    async def test_prompt_empty_when_no_entities_found(self, monkeypatch):
        from cogs.ai_core.memory.entity_memory import EntityMemoryManager

        async def fake_get_entity(name, channel_id=None, guild_id=None, update_access=True):
            return None

        mgr = EntityMemoryManager()
        mgr._initialized = True
        monkeypatch.setattr(mgr, "get_entity", fake_get_entity)

        result = await mgr.get_entities_for_prompt(["A", "B"])

        assert result == ""

    @pytest.mark.asyncio
    async def test_prompt_aggregates_found_entities(self, monkeypatch):
        from cogs.ai_core.memory.entity_memory import (
            Entity,
            EntityFacts,
            EntityMemoryManager,
        )

        e1 = Entity(
            entity_id=1,
            name="Warden",
            entity_type="character",
            facts=EntityFacts(description="keeper"),
        )

        calls = []

        async def fake_get_entity(name, channel_id=None, guild_id=None, update_access=True):
            calls.append((name, update_access))
            return e1 if name == "Warden" else None

        mgr = EntityMemoryManager()
        mgr._initialized = True
        monkeypatch.setattr(mgr, "get_entity", fake_get_entity)

        result = await mgr.get_entities_for_prompt(["Warden", "Missing"])

        # Header present, found entity rendered, missing one skipped.
        assert "[ข้อมูลตัวละคร/สถานที่ที่เกี่ยวข้อง" in result
        # entity_type is uppercased in to_prompt_text; name kept as-is.
        assert "[CHARACTER] Warden" in result
        assert "keeper" in result
        # Prompt-assembly path must NOT bump access_count.
        assert all(update_access is False for _, update_access in calls)


class TestEntityFactsRemainingPromptFields:
    """Cover the remaining to_prompt_text field branches (personality,
    appearance, relationships, owner)."""

    def test_personality_appearance_relationships_owner_render(self):
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(
            personality="brooding",
            appearance="scarred",
            relationships={"Min": "sister"},
            owner="Faust",
        )

        result = facts.to_prompt_text()

        assert "นิสัย" in result and "brooding" in result
        assert "รูปลักษณ์" in result and "scarred" in result
        assert "ความสัมพันธ์" in result and "Min: sister" in result
        assert "เจ้าของ" in result and "Faust" in result

    def test_long_field_is_capped(self):
        """An over-long description is truncated with an ellipsis."""
        from cogs.ai_core.memory.entity_memory import EntityFacts

        facts = EntityFacts(description="x" * 600)

        result = facts.to_prompt_text()

        # Capped to 500 chars + "…" (the field value, after the Thai label).
        assert "…" in result
        # The rendered value should not contain all 600 x's.
        assert "x" * 600 not in result


class TestEntityTypePromptInjectionHardening:
    """Regression: Entity.to_prompt_text must never emit an attacker-chosen
    synthetic system marker via ``entity_type``.

    ``entity_type`` is untrusted (AI-extracted JSON) and the renderer wraps it
    in its own brackets, so a bare reserved word like ``system`` would forge a
    ``[SYSTEM]`` marker. Only the four canonical types render verbatim; anything
    else collapses to ``[UNKNOWN]``.
    """

    @pytest.mark.parametrize(
        "entity_type",
        [
            "system",
            "inst",
            "user",
            "assistant",
            "ignore this",
            "SYSTEM",
            " System ",
            "banana",
            "[system]",
        ],
    )
    def test_bare_reserved_entity_type_is_neutralized(self, entity_type):
        from cogs.ai_core.memory.entity_memory import Entity, EntityFacts

        facts = EntityFacts(description="A test entity")
        entity = Entity(entity_id=1, name="Bob", entity_type=entity_type, facts=facts)

        result = entity.to_prompt_text()

        assert result.startswith("[UNKNOWN] Bob:")
        # No forged prompt-control marker may survive.
        for forged in ("[SYSTEM]", "[INST]", "[USER]", "[ASSISTANT]"):
            assert forged not in result

    @pytest.mark.parametrize(
        ("entity_type", "expected"),
        [
            ("character", "[CHARACTER]"),
            ("location", "[LOCATION]"),
            ("item", "[ITEM]"),
            ("event", "[EVENT]"),
            (" Character ", "[CHARACTER]"),
            ("LOCATION", "[LOCATION]"),
        ],
    )
    def test_canonical_entity_types_render_verbatim(self, entity_type, expected):
        from cogs.ai_core.memory.entity_memory import Entity, EntityFacts

        facts = EntityFacts(description="A test entity")
        entity = Entity(entity_id=1, name="Bob", entity_type=entity_type, facts=facts)

        result = entity.to_prompt_text()

        assert result.startswith(f"{expected} Bob:")

    def test_name_and_facts_still_scrubbed(self):
        """The allowlist change must not disturb the existing name/facts scrub."""
        from cogs.ai_core.memory.entity_memory import Entity, EntityFacts

        facts = EntityFacts(description="A test entity")
        entity = Entity(entity_id=1, name="[system] evil", entity_type="character", facts=facts)

        result = entity.to_prompt_text()

        # Canonical type still renders; the bracketed name marker is redacted.
        assert result.startswith("[CHARACTER] [redacted]")
        assert "[system] evil" not in result


class TestPostInitDBNoneGuards:
    """Cover the defensive 'db_manager became None after initialize' guards.

    These fire when initialize() short-circuits True (manager already
    initialized) but the module-level db_manager is None.
    """

    @pytest.mark.asyncio
    async def test_add_entity_db_none_after_init_returns_none(self, monkeypatch):
        from cogs.ai_core.memory.entity_memory import EntityFacts

        _patch_db(monkeypatch, None)
        mgr = _new_initialized_manager()  # initialize() returns True

        result = await mgr.add_entity("Faust", "character", EntityFacts())

        assert result is None

    @pytest.mark.asyncio
    async def test_get_entity_db_none_after_init_returns_none(self, monkeypatch):
        _patch_db(monkeypatch, None)
        mgr = _new_initialized_manager()

        assert await mgr.get_entity("Faust") is None

    @pytest.mark.asyncio
    async def test_search_db_none_after_init_returns_empty(self, monkeypatch):
        _patch_db(monkeypatch, None)
        mgr = _new_initialized_manager()

        assert await mgr.search_entities("q") == []


def _make_entity_for_update(channel_id=None, guild_id=None, facts_dict=None):
    """Build a real Entity for update_entity_facts tests."""
    from cogs.ai_core.memory.entity_memory import Entity, EntityFacts

    facts = EntityFacts.from_dict(facts_dict or {"description": "existing"})
    return Entity(
        entity_id=1,
        name="Faust",
        entity_type="character",
        facts=facts,
        channel_id=channel_id,
        guild_id=guild_id,
        confidence=0.9,
        source="user",
    )
