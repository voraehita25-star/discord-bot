"""
Re-index AI History IDs Script
Re-numbers all IDs in ai_history table to start from 1 sequentially.

IMPORTANT: Run this while the bot is STOPPED to avoid conflicts.
"""

import asyncio
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import aiosqlite

# Anchor paths to the project root so the script works regardless of cwd
# (otherwise the destructive DROP+RENAME could target a stray empty DB
# created next to the current dir).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = str(_PROJECT_ROOT / "data" / "bot_database.db")
BACKUP_DIR = _PROJECT_ROOT / "data" / "backups"


async def reindex_ai_history():
    """Re-index all IDs in ai_history table to be sequential starting from 1.

    Re-numbering primary keys is destructive: any external references to
    ``ai_history.id`` (exported JSON dumps, audit-log links, third-party
    tools that cached IDs) will silently break. The script refuses to
    run if foreign-key constraints from other tables target ai_history.
    """

    # Create backup directory (one-shot CLI script — sync path I/O is acceptable)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Backup database first. shutil.copy2 doesn't capture WAL/SHM, so the
    # operator-facing prompt below MUST happen with the bot stopped.
    backup_name = f"bot_before_reindex_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = BACKUP_DIR / backup_name
    shutil.copy2(DB_PATH, backup_path)
    # Also try to copy WAL/SHM siblings if present so the backup is
    # actually consistent — without them the .db alone is a partial view.
    for suffix in ("-wal", "-shm"):
        sibling = Path(DB_PATH + suffix)
        if sibling.exists():
            try:
                shutil.copy2(sibling, BACKUP_DIR / (backup_name + suffix))
            except OSError as e:
                print(f"[WARN] Could not back up {sibling.name}: {e}")
    print(f"[OK] Backup created: {backup_path}")

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        # Refuse to run if any other table references ai_history(id) — the
        # FK constraint would either be invalidated or silently corrupt
        # rows after the table swap. Operator must manually drop/recreate.
        cursor = await conn.execute("PRAGMA foreign_key_list('ai_history')")
        await cursor.fetchall()
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'ai_history'"
        )
        other_tables = [r["name"] for r in await cursor.fetchall()]
        for tbl in other_tables:
            try:
                cursor = await conn.execute(f"PRAGMA foreign_key_list('{tbl}')")
                fks = await cursor.fetchall()
                for fk in fks:
                    if fk["table"] == "ai_history":
                        print(
                            f"[ERROR] Refusing to run: table {tbl!r} has a "
                            f"FOREIGN KEY referencing ai_history. Renumbering "
                            f"would invalidate it."
                        )
                        return
            except Exception:
                pass

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

        # Wrap the destructive section in an explicit transaction so an
        # interrupt between DROP TABLE ai_history and the RENAME doesn't
        # leave the DB without a real ai_history table (= permanent data loss).
        # If anything below raises, the `with` exits via exception and we
        # ROLLBACK in the except block.
        try:
            await conn.execute("BEGIN IMMEDIATE")
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
                await conn.execute("ROLLBACK")
                print("[ROLLBACK] Rolled back changes")
                return

            print(f"[OK] Copied {new_rows} rows successfully")

            # Step 4: Drop old table and rename new one
            print("[STEP] Replacing old table...")
            await conn.execute("DROP TABLE ai_history")
            await conn.execute("ALTER TABLE ai_history_new RENAME TO ai_history")

            # Step 4b: Checkpoint the WAL to truncate it before we commit.
            # If the operator crashes here without a checkpoint, the WAL
            # contains a torn DROP+RENAME pair that some recovery paths
            # have historically misreplayed (DROP of a now-renamed table).
            # Truncating now keeps the on-disk DB self-describing.
            try:
                await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception as e:
                # Checkpoint is best-effort durability — log but don't fail
                # the migration on a checkpoint refusal (e.g. another
                # reader holds the WAL).
                print(f"  [WARN] wal_checkpoint(TRUNCATE) failed: {e}")

            # Step 5: Recreate every index that existed on the original table
            print(f"[STEP] Recreating {len(index_defs)} index(es)...")
            for idx_name, idx_sql in index_defs:
                try:
                    await conn.execute(idx_sql)
                    print(f"  [OK] Recreated index: {idx_name}")
                except Exception as e:
                    print(f"  [WARN] Could not recreate index {idx_name}: {e}")

            # Step 6: Verify FK integrity before committing. The pre-flight
            # check above bails on declared FKs to ai_history, but a future
            # schema change could slip past it. foreign_key_check returns
            # one row per broken FK; non-empty result = abort the migration.
            cursor = await conn.execute("PRAGMA foreign_key_check")
            broken = await cursor.fetchall()
            if broken:
                print(
                    f"[ERROR] foreign_key_check found {len(broken)} broken row(s) "
                    "after rename — rolling back to preserve referential integrity."
                )
                for b in broken[:10]:
                    print(f"  - {dict(b)}")
                await conn.execute("ROLLBACK")
                return

            # Commit. A failure here is fatal — at this point the
            # rename is durable in the WAL; calling ROLLBACK after a
            # failed commit is undefined and can corrupt the DB
            # (sqlite docs explicitly say not to do it). Log and bail.
            try:
                await conn.commit()
            except Exception as commit_err:
                print(f"[FATAL] commit() failed after DROP+RENAME: {commit_err}")
                print(f"[FATAL] DO NOT manually rollback. Restore from {backup_path}.")
                sys.exit(1)
        except BaseException:
            # This catch fires for failures BEFORE commit (the only place
            # where ROLLBACK is meaningful). Post-commit failures bail
            # via sys.exit(1) above and never reach here.
            print("[ROLLBACK] Aborting — restoring original table from transaction log")
            try:
                await conn.execute("ROLLBACK")
            except Exception:
                pass
            raise

        # Verify new ID range
        cursor = await conn.execute("SELECT MIN(id) as min_id, MAX(id) as max_id FROM ai_history")
        row = await cursor.fetchone()
        print(f"[OK] New ID range: {row['min_id']} - {row['max_id']}")

        # VACUUM cannot run inside a transaction; we already committed above.
        # Disable autocommit-style implicit txn before running it.
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
