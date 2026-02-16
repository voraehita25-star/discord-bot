"""Export SQLite database to readable JSON files."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "bot_database.db"
OUTPUT_DIR = Path(__file__).parent.parent.parent / "data" / "db_export"


def main() -> None:
    """Export all database tables to JSON files."""
    # Create output directory
    OUTPUT_DIR.mkdir(exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all tables
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'"
    )
    tables: list[str] = [row[0] for row in cursor.fetchall()]

    # Export each table to JSON
    # SECURITY NOTE: table names come from sqlite_master (trusted source).
    # We still validate and bracket-escape as defense-in-depth.
    summary: dict[str, int] = {}
    for table in tables:
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
            print(f"Skipping table with invalid name: {table}")
            continue
        cursor.execute(f"SELECT * FROM [{table}]")  # nosec: validated + bracket-escaped
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
    conn.close()


if __name__ == "__main__":
    main()
