"""
Re-index AI History IDs Script
Re-numbers all IDs in ai_history table to start from 1 sequentially.

IMPORTANT: Run this while the bot is STOPPED to avoid conflicts.
"""

import asyncio
import shutil
from datetime import datetime
from pathlib import Path

import aiosqlite

DB_PATH = "data/bot_database.db"
BACKUP_DIR = Path("data/backups")


async def reindex_ai_history():
    """Re-index all IDs in ai_history table to be sequential starting from 1."""

    # Create backup directory
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

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

        # Step 1: Create new table with same schema
        print("[STEP] Creating temporary table...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_history_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                message_id INTEGER,
                timestamp TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Step 2: Copy data ordered by original ID (so order is preserved)
        # The new AUTO INCREMENT will assign 1, 2, 3, ...
        print("[STEP] Copying data with new IDs...")
        await conn.execute("""
            INSERT INTO ai_history_new (channel_id, role, content, message_id, timestamp, created_at)
            SELECT channel_id, role, content, message_id, timestamp, created_at
            FROM ai_history
            ORDER BY id ASC
        """)

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

        # Step 5: Recreate index
        print("[STEP] Recreating indexes...")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ai_history_channel ON ai_history(channel_id)"
        )

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
