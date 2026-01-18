"""
Add local_id column to ai_history table.
This adds a per-channel sequential ID starting from 1.

IMPORTANT: Run this while the bot is STOPPED.
"""

import asyncio
import shutil
from datetime import datetime
from pathlib import Path

import aiosqlite

DB_PATH = "data/bot_database.db"
BACKUP_DIR = Path("data/backups")


async def add_local_id_column():
    """Add local_id column to ai_history and populate with per-channel sequential IDs."""

    # Create backup
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_name = f"bot_before_localid_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = BACKUP_DIR / backup_name
    shutil.copy2(DB_PATH, backup_path)
    print(f"[OK] Backup created: {backup_path}")

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        # Check if local_id column already exists
        cursor = await conn.execute("PRAGMA table_info(ai_history)")
        columns = [row["name"] for row in await cursor.fetchall()]

        if "local_id" in columns:
            print("[INFO] local_id column already exists, will update values")
        else:
            print("[STEP] Adding local_id column...")
            await conn.execute("ALTER TABLE ai_history ADD COLUMN local_id INTEGER")

        # Get all unique channels
        cursor = await conn.execute("SELECT DISTINCT channel_id FROM ai_history")
        channels = [row["channel_id"] for row in await cursor.fetchall()]
        print(f"[INFO] Found {len(channels)} channels to process")

        # Update local_id for each channel
        for channel_id in channels:
            print(f"[STEP] Processing channel {channel_id}...")

            # Get all rows for this channel ordered by id
            cursor = await conn.execute(
                "SELECT id FROM ai_history WHERE channel_id = ? ORDER BY id ASC", (channel_id,)
            )
            rows = await cursor.fetchall()

            # Update local_id with sequential values
            for idx, row in enumerate(rows, start=1):
                await conn.execute(
                    "UPDATE ai_history SET local_id = ? WHERE id = ?", (idx, row["id"])
                )

            print(f"  -> Updated {len(rows)} rows (local_id: 1 - {len(rows)})")

        await conn.commit()

        # Verify
        cursor = await conn.execute("""
            SELECT channel_id, MIN(local_id) as min_lid, MAX(local_id) as max_lid, COUNT(*) as cnt
            FROM ai_history
            GROUP BY channel_id
        """)
        print("\n[RESULT] Per-channel local_id ranges:")
        print("Channel ID           | Min | Max | Count")
        print("-" * 50)
        for row in await cursor.fetchall():
            print(f"{row['channel_id']} | {row['min_lid']:3} | {row['max_lid']:3} | {row['cnt']}")

    print("\n[DONE] local_id column added and populated!")
    print(f"[INFO] Backup at: {backup_path}")


if __name__ == "__main__":
    import sys

    print("=" * 50)
    print("Add local_id Column Script")
    print("=" * 50)

    if "--force" in sys.argv:
        asyncio.run(add_local_id_column())
    else:
        print("\n[WARNING] Make sure the bot is STOPPED!\n")
        confirm = input("Type 'yes' to proceed: ")
        if confirm.lower() == "yes":
            asyncio.run(add_local_id_column())
        else:
            print("[ABORT] Cancelled")
