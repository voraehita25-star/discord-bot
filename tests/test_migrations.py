"""
Unit Tests for the Database Migration System.

Covers utils/database/migrations.py: the versioned, sequential SQL migration
runner. Tests run against hermetic temp SQLite databases (aiosqlite) and a
monkeypatched MIGRATIONS_DIR populated with synthetic .sql files, so no real
schema files or production database are touched.
"""

from __future__ import annotations

# Add project root to path
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))


def _write_migration(directory: Path, name: str, sql: str) -> Path:
    """Helper: write a migration file into ``directory`` and return its path."""
    path = directory / name
    path.write_text(sql, encoding="utf-8")
    return path


class TestEnsureMigrationTable:
    """Test ensure_migration_table()."""

    @pytest.mark.asyncio
    async def test_creates_schema_version_table(self, temp_db: str) -> None:
        import aiosqlite

        from utils.database.migrations import ensure_migration_table

        async with aiosqlite.connect(temp_db) as conn:
            await ensure_migration_table(conn)

            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            row = await cursor.fetchone()
            assert row is not None
            assert row[0] == "schema_version"

    @pytest.mark.asyncio
    async def test_expected_columns(self, temp_db: str) -> None:
        import aiosqlite

        from utils.database.migrations import ensure_migration_table

        async with aiosqlite.connect(temp_db) as conn:
            await ensure_migration_table(conn)

            cursor = await conn.execute("PRAGMA table_info(schema_version)")
            columns = {row[1] for row in await cursor.fetchall()}
            assert {"version", "filename", "applied_at", "checksum"} <= columns

    @pytest.mark.asyncio
    async def test_idempotent_no_error_on_second_call(self, temp_db: str) -> None:
        """Calling ensure_migration_table twice must not raise (IF NOT EXISTS)."""
        import aiosqlite

        from utils.database.migrations import ensure_migration_table

        async with aiosqlite.connect(temp_db) as conn:
            await ensure_migration_table(conn)
            # Insert a row, then ensure again — must not be dropped/recreated.
            await conn.execute("INSERT INTO schema_version (version, filename) VALUES (1, 'x.sql')")
            await conn.commit()
            await ensure_migration_table(conn)

            cursor = await conn.execute("SELECT COUNT(*) FROM schema_version")
            row = await cursor.fetchone()
            assert row[0] == 1


class TestGetCurrentVersion:
    """Test get_current_version()."""

    @pytest.mark.asyncio
    async def test_fresh_db_returns_zero(self, temp_db: str) -> None:
        import aiosqlite

        from utils.database.migrations import get_current_version

        async with aiosqlite.connect(temp_db) as conn:
            # Creates the table as a side effect and returns 0 for empty table.
            version = await get_current_version(conn)
            assert version == 0

    @pytest.mark.asyncio
    async def test_returns_max_version(self, temp_db: str) -> None:
        import aiosqlite

        from utils.database.migrations import ensure_migration_table, get_current_version

        async with aiosqlite.connect(temp_db) as conn:
            await ensure_migration_table(conn)
            await conn.execute("INSERT INTO schema_version (version, filename) VALUES (3, 'c.sql')")
            await conn.execute("INSERT INTO schema_version (version, filename) VALUES (1, 'a.sql')")
            await conn.commit()

            version = await get_current_version(conn)
            assert version == 3

    @pytest.mark.asyncio
    async def test_creates_table_if_missing(self, temp_db: str) -> None:
        """get_current_version should create the tracking table if absent."""
        import aiosqlite

        from utils.database.migrations import get_current_version

        async with aiosqlite.connect(temp_db) as conn:
            await get_current_version(conn)
            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
            )
            assert await cursor.fetchone() is not None


class TestDiscoverMigrations:
    """Test discover_migrations() filename parsing and ordering."""

    def test_returns_empty_when_dir_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from utils.database import migrations

        missing = tmp_path / "does_not_exist"
        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", missing)
        assert migrations.discover_migrations() == []

    def test_returns_empty_when_dir_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        assert migrations.discover_migrations() == []

    def test_discovers_and_sorts_by_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(tmp_path, "003_third.sqlite.sql", "SELECT 1;")
        _write_migration(tmp_path, "001_first.sqlite.sql", "SELECT 1;")
        _write_migration(tmp_path, "002_second.sqlite.sql", "SELECT 1;")

        result = migrations.discover_migrations()
        versions = [v for v, _ in result]
        assert versions == [1, 2, 3]
        # Paths come back as the actual files.
        assert all(isinstance(p, Path) for _, p in result)

    def test_accepts_legacy_sql_naming(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(tmp_path, "005_legacy.sql", "SELECT 1;")

        result = migrations.discover_migrations()
        assert result == [(5, tmp_path / "005_legacy.sql")]

    def test_prefers_sqlite_sql_over_legacy_for_same_version(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(tmp_path, "007_thing.sql", "SELECT 1;")
        _write_migration(tmp_path, "007_thing.sqlite.sql", "SELECT 2;")

        result = migrations.discover_migrations()
        assert len(result) == 1
        version, path = result[0]
        assert version == 7
        assert path.name == "007_thing.sqlite.sql"

    def test_skips_invalid_filenames(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        # Valid
        _write_migration(tmp_path, "001_ok.sqlite.sql", "SELECT 1;")
        # Invalid: no 3-digit prefix
        _write_migration(tmp_path, "1_bad.sql", "SELECT 1;")
        # Invalid: uppercase in description (pattern requires [a-z0-9_])
        _write_migration(tmp_path, "002_BadName.sql", "SELECT 1;")
        # Invalid: missing underscore separator
        _write_migration(tmp_path, "003badname.sql", "SELECT 1;")
        # Non-sql file entirely (glob is *.sql so it's never seen)
        _write_migration(tmp_path, "notes.txt", "ignore me")

        result = migrations.discover_migrations()
        assert [v for v, _ in result] == [1]

    def test_lowercase_digits_underscore_description_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(tmp_path, "012_bump_default_model_opus_4_8.sqlite.sql", "SELECT 1;")

        result = migrations.discover_migrations()
        assert result == [(12, tmp_path / "012_bump_default_model_opus_4_8.sqlite.sql")]


class TestRunMigrations:
    """Test run_migrations() end-to-end against a temp SQLite DB."""

    @pytest.mark.asyncio
    async def test_fresh_db_applies_all_and_tracks(
        self, temp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import aiosqlite

        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(
            tmp_path,
            "001_create_widgets.sqlite.sql",
            "CREATE TABLE widgets (id INTEGER PRIMARY KEY, name TEXT);",
        )
        _write_migration(
            tmp_path,
            "002_add_color.sqlite.sql",
            "ALTER TABLE widgets ADD COLUMN color TEXT;",
        )

        async with aiosqlite.connect(temp_db) as conn:
            applied = await migrations.run_migrations(conn)
            assert applied == 2

            # The real table was created and altered.
            cursor = await conn.execute("PRAGMA table_info(widgets)")
            cols = {row[1] for row in await cursor.fetchall()}
            assert cols == {"id", "name", "color"}

            # Version tracking is correct.
            cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
            assert (await cursor.fetchone())[0] == 2

            # Both rows recorded with filenames + checksums.
            cursor = await conn.execute(
                "SELECT version, filename, checksum FROM schema_version ORDER BY version"
            )
            rows = await cursor.fetchall()
            assert [r[0] for r in rows] == [1, 2]
            assert rows[0][1] == "001_create_widgets.sqlite.sql"
            assert rows[1][1] == "002_add_color.sqlite.sql"
            assert all(r[2] for r in rows)  # checksums are non-empty

    @pytest.mark.asyncio
    async def test_idempotent_second_run_applies_nothing(
        self, temp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import aiosqlite

        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(
            tmp_path,
            "001_create_widgets.sqlite.sql",
            "CREATE TABLE widgets (id INTEGER PRIMARY KEY);",
        )

        async with aiosqlite.connect(temp_db) as conn:
            first = await migrations.run_migrations(conn)
            assert first == 1

            second = await migrations.run_migrations(conn)
            assert second == 0

            # No duplicate tracking rows.
            cursor = await conn.execute("SELECT COUNT(*) FROM schema_version")
            assert (await cursor.fetchone())[0] == 1

    @pytest.mark.asyncio
    async def test_only_applies_pending_versions(
        self, temp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When version 1 is already applied, only 2 and 3 should run."""
        import aiosqlite

        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(tmp_path, "001_a.sqlite.sql", "CREATE TABLE a (id INTEGER);")
        _write_migration(tmp_path, "002_b.sqlite.sql", "CREATE TABLE b (id INTEGER);")
        _write_migration(tmp_path, "003_c.sqlite.sql", "CREATE TABLE c (id INTEGER);")

        async with aiosqlite.connect(temp_db) as conn:
            # Pretend version 1 already applied (and its table exists).
            await migrations.ensure_migration_table(conn)
            await conn.execute("CREATE TABLE a (id INTEGER)")
            await conn.execute(
                "INSERT INTO schema_version (version, filename) VALUES (1, '001_a.sqlite.sql')"
            )
            await conn.commit()

            applied = await migrations.run_migrations(conn)
            assert applied == 2

            cursor = await conn.execute("SELECT version FROM schema_version ORDER BY version")
            assert [r[0] for r in await cursor.fetchall()] == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_returns_zero_when_no_migrations(
        self, temp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import aiosqlite

        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)

        async with aiosqlite.connect(temp_db) as conn:
            applied = await migrations.run_migrations(conn)
            assert applied == 0

    @pytest.mark.asyncio
    async def test_multi_statement_migration(
        self, temp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A single migration file with several statements applies all of them."""
        import aiosqlite

        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(
            tmp_path,
            "001_multi.sqlite.sql",
            "CREATE TABLE t1 (id INTEGER);\n"
            "CREATE TABLE t2 (id INTEGER);\n"
            "INSERT INTO t1 (id) VALUES (42);\n",
        )

        async with aiosqlite.connect(temp_db) as conn:
            applied = await migrations.run_migrations(conn)
            assert applied == 1

            cursor = await conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('t1','t2')"
            )
            names = {r[0] for r in await cursor.fetchall()}
            assert names == {"t1", "t2"}

            cursor = await conn.execute("SELECT id FROM t1")
            assert (await cursor.fetchone())[0] == 42

    @pytest.mark.asyncio
    async def test_comments_with_semicolons_do_not_split(
        self, temp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Line/block comments containing ';' must not split a statement."""
        import aiosqlite

        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        sql = (
            "-- a leading comment; with a semicolon\n"
            "/* block comment; also has; semicolons */\n"
            "CREATE TABLE notes (\n"
            "    id INTEGER PRIMARY KEY,  -- inline comment; here\n"
            "    body TEXT\n"
            ");\n"
            "INSERT INTO notes (id, body) VALUES (1, 'hello');\n"
        )
        _write_migration(tmp_path, "001_comments.sqlite.sql", sql)

        async with aiosqlite.connect(temp_db) as conn:
            applied = await migrations.run_migrations(conn)
            assert applied == 1

            cursor = await conn.execute("SELECT body FROM notes WHERE id = 1")
            assert (await cursor.fetchone())[0] == "hello"

    @pytest.mark.asyncio
    async def test_failed_migration_rolls_back_and_raises(
        self, temp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A bad SQL statement raises RuntimeError and does not record the version."""
        import aiosqlite

        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(
            tmp_path,
            "001_good.sqlite.sql",
            "CREATE TABLE good (id INTEGER);",
        )
        _write_migration(
            tmp_path,
            "002_broken.sqlite.sql",
            "THIS IS NOT VALID SQL;",
        )

        async with aiosqlite.connect(temp_db) as conn:
            with pytest.raises(RuntimeError) as exc:
                await migrations.run_migrations(conn)

            # Error message names the failing migration.
            assert "Migration 2" in str(exc.value)
            assert "002_broken.sqlite.sql" in str(exc.value)

            # Migration 1 committed before 2 failed; 2 must NOT be recorded.
            cursor = await conn.execute("SELECT version FROM schema_version ORDER BY version")
            recorded = [r[0] for r in await cursor.fetchall()]
            assert recorded == [1]

    @pytest.mark.asyncio
    async def test_checksum_is_deterministic_truncated_sha256(
        self, temp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The recorded checksum equals the first 16 hex chars of sha256(sql)."""
        import hashlib

        import aiosqlite

        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        sql = "CREATE TABLE c (id INTEGER);"
        _write_migration(tmp_path, "001_c.sqlite.sql", sql)
        expected = hashlib.sha256(sql.encode()).hexdigest()[:16]

        async with aiosqlite.connect(temp_db) as conn:
            await migrations.run_migrations(conn)
            cursor = await conn.execute("SELECT checksum FROM schema_version WHERE version = 1")
            assert (await cursor.fetchone())[0] == expected

    @pytest.mark.asyncio
    async def test_foreign_keys_reasserted_after_apply(
        self, temp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After applying at least one migration, PRAGMA foreign_keys is ON."""
        import aiosqlite

        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(tmp_path, "001_fk.sqlite.sql", "CREATE TABLE fk (id INTEGER);")

        async with aiosqlite.connect(temp_db) as conn:
            # Start with FK off to prove run_migrations turns it on.
            await conn.execute("PRAGMA foreign_keys=OFF")
            await migrations.run_migrations(conn)

            cursor = await conn.execute("PRAGMA foreign_keys")
            assert (await cursor.fetchone())[0] == 1

    @pytest.mark.asyncio
    async def test_invalid_filename_in_dir_is_ignored_during_run(
        self, temp_db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An invalidly named .sql file in the dir is skipped, not applied."""
        import aiosqlite

        from utils.database import migrations

        monkeypatch.setattr(migrations, "MIGRATIONS_DIR", tmp_path)
        _write_migration(tmp_path, "001_valid.sqlite.sql", "CREATE TABLE v (id INTEGER);")
        # Would explode if it were ever executed.
        _write_migration(tmp_path, "bad_name.sql", "DROP TABLE v; GARBAGE;")

        async with aiosqlite.connect(temp_db) as conn:
            applied = await migrations.run_migrations(conn)
            assert applied == 1

            cursor = await conn.execute("SELECT version FROM schema_version")
            assert [r[0] for r in await cursor.fetchall()] == [1]


class TestModuleConstants:
    """Sanity checks on module-level constants."""

    def test_migrations_dir_points_at_repo_migrations_folder(self) -> None:
        from utils.database import migrations

        assert migrations.MIGRATIONS_DIR.name == "migrations"
        assert migrations.MIGRATIONS_DIR.parent.name == "maintenance"

    def test_real_migration_files_discoverable(self) -> None:
        """The actual repo migration files parse with the real MIGRATIONS_DIR."""
        from utils.database import migrations

        # Uses the real directory (no monkeypatch) — just confirm sane output.
        result = migrations.discover_migrations()
        # Repo ships numbered migrations; versions must be unique and sorted.
        versions = [v for v, _ in result]
        assert versions == sorted(versions)
        assert len(versions) == len(set(versions))
