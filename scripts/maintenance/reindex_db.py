"""
Re-index AI History IDs Script
Re-numbers all IDs in ai_history table to start from 1 sequentially.

IMPORTANT: Run this while the bot is STOPPED to avoid conflicts.
"""

import asyncio
import re
import shutil
from datetime import datetime
from pathlib import Path

import aiosqlite

DB_PATH = "data/bot_database.db"
BACKUP_DIR = Path("data/backups")


async def reindex_ai_history():
    """Re-index all IDs in ai_history table to be sequential starting from 1."""

    # Create backup directory (one-shot CLI script — sync path I/O is acceptable)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240

    # Backup database first
    backup_name = f"bot_before_reindex_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = BACKUP_DIR / backup_name
    shutil.copy2(DB_PATH, backup_path)
    print(f"[OK] Backup created: {backup_path}")

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        # Get current row count
        cursor = await conn.execute("SELECT COUNT(*) as count FROM ai_history")
        row = await cursor.fetchone()
        total_rows = row["count"]
        print(f"[INFO] Total rows to re-index: {total_rows}")

        if total_rows == 0:
            print("[WARN] No data to re-index")
            return

        # Get current ID range
        cursor = await conn.execute("SELECT MIN(id) as min_id, MAX(id) as max_id FROM ai_history")
        row = await cursor.fetchone()
        print(f"[INFO] Current ID range: {row['min_id']} - {row['max_id']}")

        # Introspect live schema so this script stays in sync with database.py
        # even after new columns are added. Hardcoding the schema historically
        # caused data loss on newly-added columns.
        cursor = await conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='ai_history'"
        )
        row = await cursor.fetchone()
        if not row or not row["sql"]:
            print("[ERROR] Could not read ai_history schema from sqlite_master")
            return
        create_sql: str = row["sql"]
        # Rewrite CREATE TABLE ai_history -> CREATE TABLE ai_history_new (preserve rest).
        new_create_sql = re.sub(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"'`]?ai_history[\"'`]?",
            "CREATE TABLE ai_history_new",
            create_sql,
            count=1,
            flags=re.IGNORECASE,
        )

        cursor = await conn.execute("PRAGMA table_info(ai_history)")
        columns = [r["name"] for r in await cursor.fetchall()]
        if "id" not in columns:
            print("[ERROR] ai_history table missing 'id' column — unexpected schema")
            return
        # Copy every column except id (AUTOINCREMENT will re-assign)
        copy_columns = [c for c in columns if c != "id"]
        col_list = ", ".join(f'"{c}"' for c in copy_columns)

        # Collect index definitions so we can recreate them on the new table.
        cursor = await conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='ai_history' AND sql IS NOT NULL"
        )
        index_defs = [(r["name"], r["sql"]) for r in await cursor.fetchall()]

        # Step 1: Create new table with introspected schema
        print("[STEP] Creating temporary table...")
        await conn.execute("DROP TABLE IF EXISTS ai_history_new")
        await conn.execute(new_create_sql)

        # Step 2: Copy data ordered by original ID (so order is preserved)
        # The new AUTO INCREMENT will assign 1, 2, 3, ...
        print("[STEP] Copying data with new IDs...")
        await conn.execute(
            f"INSERT INTO ai_history_new ({col_list}) "
            f"SELECT {col_list} FROM ai_history ORDER BY id ASC"
        )

        # Step 3: Verify row count matches
        cursor = await conn.execute("SELECT COUNT(*) as count FROM ai_history_new")
        row = await cursor.fetchone()
        new_rows = row["count"]

        if new_rows != total_rows:
            print(f"[ERROR] Row count mismatch! Original: {total_rows}, New: {new_rows}")
            await conn.execute("DROP TABLE ai_history_new")
            print("[ROLLBACK] Rolled back changes")
            return

        print(f"[OK] Copied {new_rows} rows successfully")

        # Step 4: Drop old table and rename new one
        print("[STEP] Replacing old table...")
        await conn.execute("DROP TABLE ai_history")
        await conn.execute("ALTER TABLE ai_history_new RENAME TO ai_history")

        # Step 5: Recreate every index that existed on the original table
        print(f"[STEP] Recreating {len(index_defs)} index(es)...")
        for idx_name, idx_sql in index_defs:
            try:
                await conn.execute(idx_sql)
                print(f"  [OK] Recreated index: {idx_name}")
            except Exception as e:
                print(f"  [WARN] Could not recreate index {idx_name}: {e}")

        await conn.commit()

        # Verify new ID range
        cursor = await conn.execute("SELECT MIN(id) as min_id, MAX(id) as max_id FROM ai_history")
        row = await cursor.fetchone()
        print(f"[OK] New ID range: {row['min_id']} - {row['max_id']}")

        # VACUUM to reclaim space
        print("[STEP] Running VACUUM to optimize database...")
        await conn.execute("VACUUM")

    print("\n[DONE] Re-indexing complete!")
    print(f"[INFO] Backup saved at: {backup_path}")
    print("[TIP] You can now restart the bot and re-export JSON files")


if __name__ == "__main__":
    print("=" * 50)
    print("AI History Re-index Script")
    print("=" * 50)
    print("\n[WARNING] Make sure the bot is STOPPED before running this!\n")

    confirm = input("Type 'yes' to proceed: ")
    if confirm.lower() == "yes":
        asyncio.run(reindex_ai_history())
    else:
        print("[ABORT] Cancelled")
