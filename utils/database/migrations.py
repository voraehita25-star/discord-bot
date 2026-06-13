"""
Database Migration System for Discord Bot.

Provides versioned, sequential SQL migrations with automatic tracking.
Migrations are stored in scripts/maintenance/migrations/ as numbered SQL files.

Usage:
    from utils.database.migrations import run_migrations
    await run_migrations(db)  # Runs any pending migrations
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import aiosqlite

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "scripts" / "maintenance" / "migrations"


async def ensure_migration_table(conn: aiosqlite.Connection) -> None:
    """Create the schema_version table if it doesn't exist."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            checksum TEXT
        )
    """)
    await conn.commit()


async def get_current_version(conn: aiosqlite.Connection) -> int:
    """Get the current schema version."""
    await ensure_migration_table(conn)
    cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    return row[0] if row and row[0] is not None else 0


def discover_migrations() -> list[tuple[int, Path]]:
    """Discover migration files in the migrations directory.

    Files must be named like: 001_description.sqlite.sql, 002_description.sqlite.sql, etc.
    The compound `.sqlite.sql` extension keeps SQLite-specific DDL (`CREATE INDEX
    IF NOT EXISTS`, partial indexes, `pragma_table_info`, `ALTER TABLE ... RENAME TO`)
    from being flagged as T-SQL errors by the VS Code mssql extension — we map
    `**/*.sqlite.sql` to `plaintext` in `.vscode/settings.json` so it skips validation.

    For backwards compatibility we also accept legacy `.sql` files (without the
    `.sqlite` infix) so databases that already applied migrations by those filenames
    keep matching on `version` (the runner tracks versions, not names).

    Returns sorted list of (version, path) tuples.
    """
    if not MIGRATIONS_DIR.exists():
        return []

    # Accept both new (.sqlite.sql) and legacy (.sql) naming.
    valid_pattern = re.compile(r"^\d{3}_[a-z0-9_]+(?:\.sqlite)?\.sql$")
    seen_versions: dict[int, Path] = {}
    for f in MIGRATIONS_DIR.glob("*.sql"):
        if not valid_pattern.match(f.name):
            logger.warning("Skipping invalid migration filename: %s", f.name)
            continue
        try:
            version = int(f.stem.split("_")[0])
        except (ValueError, IndexError):
            logger.warning("Skipping invalid migration filename: %s", f.name)
            continue
        # Prefer .sqlite.sql over .sql when both exist for the same version.
        existing = seen_versions.get(version)
        if existing is None or (
            f.name.endswith(".sqlite.sql") and not existing.name.endswith(".sqlite.sql")
        ):
            seen_versions[version] = f

    return sorted(seen_versions.items(), key=lambda x: x[0])


async def run_migrations(conn: aiosqlite.Connection) -> int:
    """Run all pending migrations.

    Args:
        conn: An open aiosqlite connection

    Returns:
        Number of migrations applied
    """
    current_version = await get_current_version(conn)
    migrations = discover_migrations()

    applied = 0
    for version, path in migrations:
        if version <= current_version:
            continue

        logger.info("📦 Applying migration %d: %s", version, path.name)

        try:
            sql = path.read_text(encoding="utf-8")

            # Execute migration statements individually within a transaction
            # (executescript auto-commits, breaking atomicity with the version record)
            checksum = hashlib.sha256(sql.encode()).hexdigest()[:16]

            statements: list[str] = []
            current: list[str] = []
            for line in sql.splitlines():
                current.append(line)
                candidate = "\n".join(current).strip()
                # Strip comments before passing to ``sqlite3.complete_statement``
                # — that builtin doesn't ignore `--` line comments or
                # `/* ... */` block comments containing semicolons, so a comment
                # with a `;` would split a statement prematurely. The inner loop
                # below reprocesses the whole accumulated ``current`` from
                # scratch each iteration (its own ``local_in_block`` tracks
                # multi-line block comments), so a separate outer state machine
                # would be redundant. We build the comment-stripped text only for
                # the completeness check and keep the original lines in
                # ``current`` so executed SQL keeps its formatting.
                # CAVEAT: this stripper is not string-literal aware — a ``--`` or
                # ``/* */`` *inside* a quoted SQL string literal would be wrongly
                # treated as a comment. No migration SQL may embed comment
                # markers inside string literals (all current migrations comply).
                check_lines: list[str] = []
                local_in_block = False
                for ln in current:
                    s = ln
                    if local_in_block:
                        e = s.find("*/")
                        if e == -1:
                            continue
                        s = s[e + 2 :]
                        local_in_block = False
                    cp = s.find("--")
                    if cp != -1:
                        s = s[:cp]
                    bs = s.find("/*")
                    if bs != -1:
                        rest_s = s[bs:]
                        be = rest_s.find("*/")
                        if be == -1:
                            local_in_block = True
                            s = s[:bs]
                        else:
                            s = s[:bs] + s[bs + be + 2 :]
                    check_lines.append(s)
                check_candidate = "\n".join(check_lines).strip()
                if check_candidate and sqlite3.complete_statement(check_candidate):
                    statements.append(candidate)
                    current = []

            trailing = "\n".join(current).strip()
            if trailing:
                statements.append(trailing)

            # NOTE: We deliberately do NOT wrap this in an explicit BEGIN.
            # Under aiosqlite's legacy isolation, leading DDL autocommits — so
            # a mid-migration crash leaves a partial schema without the
            # version row — but the rebuild migrations (003/007/010/011/012/
            # 016) guard against that with `DROP TABLE IF EXISTS <x>_new`,
            # making a re-run safe. An explicit BEGIN would turn migration
            # 010's `PRAGMA foreign_keys=OFF` into a no-op (SQLite ignores it
            # inside a transaction), so the subsequent DROP TABLE would
            # ON DELETE CASCADE-wipe dashboard_messages — data loss. Leave
            # DDL autocommitting.
            for stmt in statements:
                await conn.execute(stmt)

            # Record the migration in the same transaction
            await conn.execute(
                "INSERT INTO schema_version (version, filename, checksum) VALUES (?, ?, ?)",
                (version, path.name, checksum),
            )
            await conn.commit()

            applied += 1
            logger.info("✅ Migration %d applied successfully", version)

        except Exception as e:
            logger.exception("❌ Migration %d failed", version)
            await conn.rollback()
            raise RuntimeError(f"Migration {version} ({path.name}) failed: {e}") from e

    if applied:
        logger.info("📦 Applied %d migration(s), now at version %d", applied, version)
        # Migration 010 issues `PRAGMA foreign_keys=OFF` for a table rebuild.
        # Its own trailing `PRAGMA foreign_keys=ON` is a no-op because it runs
        # inside the still-open implicit transaction (SQLite ignores the pragma
        # mid-transaction). Re-assert it here — after the final commit, with no
        # transaction open — so this connection isn't returned with FK
        # enforcement silently disabled. (The pool also re-asserts on every
        # acquisition; this keeps the migration self-contained.)
        await conn.execute("PRAGMA foreign_keys=ON")
    else:
        logger.debug("📦 Database schema is up to date (version %d)", current_version)

    return applied
