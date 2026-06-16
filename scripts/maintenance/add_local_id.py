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

# Anchor paths to the project root so the backup and DB open hit the
# real files regardless of cwd. Without this the PID-file check below
# (which IS anchored) would say "bot is stopped" while we silently
# created an empty DB next to the current dir.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = str(_PROJECT_ROOT / "data" / "bot_database.db")
BACKUP_DIR = _PROJECT_ROOT / "data" / "backups"


async def add_local_id_column():
    """Add local_id column to ai_history and populate with per-channel sequential IDs."""

    # Create backup (one-shot CLI script — sync path I/O is acceptable)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_name = f"bot_before_localid_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = BACKUP_DIR / backup_name
    shutil.copy2(DB_PATH, backup_path)
    print(f"[OK] Backup created: {backup_path}")

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        # Disable Python's implicit BEGIN so we control the transaction.
        # Without this, sqlite3's default 'deferred' mode acquires a SHARED
        # lock first and only upgrades to RESERVED on the first write — that
        # leaves a window where another writer (a forgotten bot process, a
        # parallel maintenance script) can interleave INSERTs between our
        # scan and our UPDATEs, producing duplicate or skipped local_ids.
        # BEGIN IMMEDIATE takes the write lock up front and serializes us
        # against any other writer.
        conn.isolation_level = None
        await conn.execute("BEGIN IMMEDIATE")

        try:
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
                    "SELECT id FROM ai_history WHERE channel_id = ? ORDER BY id ASC",
                    (channel_id,),
                )
                rows = await cursor.fetchall()

                # Update local_id with sequential values
                for idx, row in enumerate(rows, start=1):
                    await conn.execute(
                        "UPDATE ai_history SET local_id = ? WHERE id = ?", (idx, row["id"])
                    )

                print(f"  -> Updated {len(rows)} rows (local_id: 1 - {len(rows)})")

            await conn.commit()
        except Exception:
            # Roll back the write lock so we don't leave the DB in
            # half-migrated state on any failure between BEGIN and commit.
            try:
                await conn.rollback()
            except Exception:
                pass
            raise

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
            # A NULL channel_id group (rows whose channel_id IS NULL never
            # matched `WHERE channel_id = ?`) yields NULL MIN/MAX, which the
            # `:3` int spec can't format — fall back to a dash so a successful
            # migration isn't masked by a TypeError.
            mn = row["min_lid"] if row["min_lid"] is not None else "-"
            mx = row["max_lid"] if row["max_lid"] is not None else "-"
            print(f"{row['channel_id']} | {mn:>3} | {mx:>3} | {row['cnt']}")

    print("\n[DONE] local_id column added and populated!")
    print(f"[INFO] Backup at: {backup_path}")


if __name__ == "__main__":
    import sys

    print("=" * 50)
    print("Add local_id Column Script")
    print("=" * 50)

    # Even with --force we must refuse to run while the bot is alive: this
    # script issues `BEGIN IMMEDIATE` + many UPDATEs against ai_history,
    # and a concurrent bot writer would race with us and corrupt the
    # local_id sequence we're trying to populate.
    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
    PID_FILE = PROJECT_ROOT / "bot.pid"
    if PID_FILE.exists():
        print(
            f"[ERROR] {PID_FILE} exists — the bot appears to be running. "
            "Stop the bot before migrating (this is enforced even with --force)."
        )
        sys.exit(1)

    if "--force" in sys.argv:
        asyncio.run(add_local_id_column())
    else:
        print("\n[WARNING] Make sure the bot is STOPPED!\n")
        confirm = input("Type 'yes' to proceed: ")
        if confirm.lower() == "yes":
            asyncio.run(add_local_id_column())
        else:
            print("[ABORT] Cancelled")
