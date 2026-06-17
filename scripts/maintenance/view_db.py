"""Export SQLite database to readable JSON files."""

from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

DB_PATH = Path(__file__).parent.parent.parent / "data" / "bot_database.db"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "db_export"


def main() -> None:
    """Export all database tables to JSON files."""
    # Create output directory (parents=True so a missing/relocated data/ dir
    # doesn't raise FileNotFoundError; matches rollback_migration._ensure_backup_dir)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Fail loudly instead of silently exporting an empty database: the default
    # read-write-create mode would CREATE an empty bot_database.db here, then
    # "export" zero tables and print success, leaving a stray file behind.
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        print("Run the bot at least once so it creates data/bot_database.db.")
        raise SystemExit(1)

    # closing() guarantees the connection is closed: sqlite3's own context
    # manager only commits/rolls back the transaction, it does NOT close the
    # connection. On Windows a leaked handle can block reindex/rollback.
    # mode=ro: this is a read-only export tool (SELECT only), so open read-only
    # to never create/checkpoint the DB or its -wal/-shm sidecars (mirrors
    # watch_history.py and rollback_migration.py).
    with closing(sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Get all tables
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
        )
        tables: list[str] = [row[0] for row in cursor.fetchall()]

        # Export each table to JSON
        # SECURITY NOTE: table names come from sqlite_master (trusted source).
        # We use a whitelist of known tables as defense-in-depth.
        from utils.database import KNOWN_TABLES

        summary: dict[str, int] = {}
        for table in tables:
            if table not in KNOWN_TABLES:
                print(f"Skipping unknown table: {table}")
                continue
            cursor.execute(f"SELECT * FROM [{table}]")  # nosec: whitelisted table name
            rows = cursor.fetchall()

            # Convert to list of dicts
            data = [dict(row) for row in rows]
            summary[table] = len(data)

            # Write to JSON file
            output_file = OUTPUT_DIR / f"{table}.json"
            output_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )

            print(f"Exported {table}: {len(data)} rows -> {output_file.name}")

        # Write summary
        summary_file = OUTPUT_DIR / "_summary.json"
        summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nAll data exported to: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
