"""
Database Migration System for Discord Bot.

Provides versioned, sequential SQL migrations with automatic tracking.
Migrations are stored in scripts/maintenance/migrations/ as numbered SQL files.

Usage:
    from utils.database.migrations import run_migrations
    await run_migrations(db)  # Runs any pending migrations
"""

from __future__ import annotations

import logging
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

    Files must be named like: 001_description.sql, 002_description.sql, etc.
    Returns sorted list of (version, path) tuples.
    """
    if not MIGRATIONS_DIR.exists():
        return []

    migrations = []
    for f in MIGRATIONS_DIR.glob("*.sql"):
        try:
            version = int(f.stem.split("_")[0])
            migrations.append((version, f))
        except (ValueError, IndexError):
            logger.warning("Skipping invalid migration filename: %s", f.name)

    return sorted(migrations, key=lambda x: x[0])


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
            import hashlib
            checksum = hashlib.sha256(sql.encode()).hexdigest()[:16]

            # Split SQL into individual statements and execute within transaction
            statements = [s.strip() for s in sql.split(';') if s.strip()]
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
            logger.error("❌ Migration %d failed: %s", version, e)
            await conn.rollback()
            raise RuntimeError(f"Migration {version} ({path.name}) failed: {e}") from e

    if applied:
        logger.info("📦 Applied %d migration(s), now at version %d", applied, version)
    else:
        logger.debug("📦 Database schema is up to date (version %d)", current_version)

    return applied
