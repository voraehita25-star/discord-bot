"""Smoke-test full database schema initialization in an isolated temp workspace."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _init_schema() -> Path:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    from utils.database.database import Database

    database = Database()
    await database.init_schema()
    await database.stop_background_tasks()
    await database.close_pool()
    return Path("data") / "bot_database.db"


def main() -> None:
    original_cwd = Path.cwd()
    expected_version = len(list((REPO_ROOT / "scripts" / "maintenance" / "migrations").glob("*.sql")))

    with tempfile.TemporaryDirectory(prefix="schema-smoke-", ignore_cleanup_errors=True) as temp_dir:
        try:
            os.chdir(temp_dir)
            db_path = asyncio.run(_init_schema())

            conn = sqlite3.connect(db_path)
            try:
                tables = [
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                    ).fetchall()
                ]
                current_version = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM schema_version"
                ).fetchone()[0]
            finally:
                conn.close()
        finally:
            os.chdir(original_cwd)

        print(f"Schema OK: {len(tables)} tables created")
        print(f"Schema version OK: {current_version}/{expected_version}")
        if len(tables) < 15:
            raise SystemExit(f"Expected >=15 tables, got {len(tables)}: {tables}")
        if current_version != expected_version:
            raise SystemExit(
                f"Expected schema_version {expected_version}, got {current_version}"
            )


if __name__ == "__main__":
    main()
