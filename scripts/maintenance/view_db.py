"""Export SQLite database to readable JSON files."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

DB_PATH = Path(__file__).parent.parent.parent / "data" / "bot_database.db"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "db_export"


def main() -> None:
    """Export all database tables to JSON files."""
    # Create output directory
    OUTPUT_DIR.mkdir(exist_ok=True)

    with sqlite3.connect(str(DB_PATH)) as conn:
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
