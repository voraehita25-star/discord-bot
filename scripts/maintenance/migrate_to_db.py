"""
Migration Script: JSON to SQLite Database
Converts existing JSON history files to the new SQLite database.

Usage:
    python scripts/maintenance/migrate_to_db.py
    python scripts/maintenance/migrate_to_db.py --dry-run   # Preview without changes
    python scripts/maintenance/migrate_to_db.py --backup    # Backup before migration
    python scripts/maintenance/migrate_to_db.py --delete-json  # Delete JSON after (needs --backup or --yes-delete-json)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add project root to path. We do NOT chdir at import time — that would
# silently change CWD for any tool that imported this module. The CLI
# entry point at the bottom of the file handles cwd via main().
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import contextlib

from utils.database import db

JsonFileGroup = list[tuple[int, Path]]
JsonFileBuckets = dict[str, JsonFileGroup]


def _extract_text(part: Any) -> str:
    """Render one history ``part`` to text. Hoisted to module scope so it's
    defined once, not rebuilt on every loop iteration (it closes over nothing
    loop-specific)."""
    if isinstance(part, str):
        return part
    if isinstance(part, dict) and "text" in part:
        text = part["text"]
        return text if isinstance(text, str) else str(text)
    return str(part)


def find_json_files() -> JsonFileBuckets:
    """Find all JSON files that need to be migrated.

    Anchored to project root so it can be called standalone (without
    relying on ``async_main`` having already done ``os.chdir``).
    """
    project_root = Path(__file__).resolve().parents[2]
    data_dir = project_root / "data"
    config_dir = project_root / "data" / "ai_config"

    files: JsonFileBuckets = {"history": [], "metadata": [], "queue": []}

    if data_dir.exists():
        # Find AI history files
        for f in data_dir.glob("ai_history_*.json"):
            try:
                channel_id = int(f.stem.replace("ai_history_", ""))
                files["history"].append((channel_id, f))
            except ValueError:
                print(f"  [!] Skipping invalid file: {f}")

        # Find queue files
        for f in data_dir.glob("queue_*.json"):
            try:
                guild_id = int(f.stem.replace("queue_", ""))
                files["queue"].append((guild_id, f))
            except ValueError:
                print(f"  [!] Skipping invalid file: {f}")

    if config_dir.exists():
        # Find metadata files
        for f in config_dir.glob("ai_metadata_*.json"):
            try:
                channel_id = int(f.stem.replace("ai_metadata_", ""))
                files["metadata"].append((channel_id, f))
            except ValueError:
                print(f"  [!] Skipping invalid file: {f}")

    return files


async def migrate_history(channel_id: int, filepath: Path, dry_run: bool = False) -> int:
    """Migrate a single history file to database.

    All inserts for one file happen inside a single explicit transaction
    (BEGIN IMMEDIATE / COMMIT). Previously each ``save_ai_message`` ran in
    its own implicit transaction, so a crash mid-file left the destination
    table half-populated AND the source JSON still on disk — making it
    impossible to tell which rows had been applied during a re-run.
    """
    from datetime import datetime, timezone

    try:
        history = json.loads(filepath.read_text(encoding="utf-8"))

        if not isinstance(history, list):
            print(f"    [!] Invalid format in {filepath}")
            return 0

        # Pre-process all items (cheap CPU work) BEFORE we open the write
        # connection so the lock is held for as little time as possible.
        rows: list[tuple[int, str, str, int | None, str]] = []
        for item in history:
            if not isinstance(item, dict):
                continue

            role = item.get("role", "user")
            # Normalize the role to the values ai_history's
            # CHECK(role IN ('user','model')) constraint permits. A hand-edited
            # file or an 'assistant'-style export would otherwise raise
            # sqlite3.IntegrityError on its INSERT and — since the whole file
            # migrates in one transaction — roll back the ENTIRE file.
            if role not in ("user", "model"):
                role = "model" if role == "assistant" else "user"
            parts = item.get("parts", [])
            message_id = item.get("message_id")
            timestamp = item.get("timestamp")

            if isinstance(parts, list):
                content = "\n".join(_extract_text(p) for p in parts if p)
            else:
                content = str(parts)

            if not content:
                continue

            ts = timestamp or datetime.now(timezone.utc).isoformat()
            rows.append((channel_id, role, content, message_id, ts))

        if dry_run:
            return len(rows)

        # Single transaction per file. ``get_write_connection`` holds the
        # write lock for the whole block and its context manager commits on
        # success / rolls back on any exception, so we either fully migrate
        # this file or leave the DB untouched. Do NOT issue a manual
        # ``BEGIN IMMEDIATE``/``COMMIT`` here: the pooled connection runs in
        # sqlite3's legacy isolation mode (isolation_level=""), where mixing
        # explicit transaction control with the driver's implicit BEGIN can
        # raise "cannot start a transaction within a transaction" and would
        # also double-commit against the context manager's own commit.
        # `count` is rows UPSERTED (insert OR update), not strictly new inserts:
        # a duplicated non-null message_id takes the ON CONFLICT DO UPDATE path,
        # so for files with duplicate ids this slightly overstates distinct rows
        # added. The authoritative figure is the separate `SELECT COUNT(*) FROM
        # ai_history` printed as Database Statistics; this is a progress tally.
        count = 0
        async with db.get_write_connection() as conn:
            for chan_id, role, content, message_id, ts in rows:
                await conn.execute(
                    """INSERT INTO ai_history (channel_id, role, content, message_id, timestamp, local_id)
                       VALUES (?, ?, ?, ?, ?,
                           (SELECT COALESCE(MAX(local_id), 0) + 1 FROM ai_history WHERE channel_id = ?))
                       ON CONFLICT(channel_id, message_id) WHERE message_id IS NOT NULL
                       DO UPDATE SET content = excluded.content""",
                    (chan_id, role, content, message_id, ts, chan_id),
                )
                count += 1

        return count

    except (json.JSONDecodeError, OSError) as e:
        print(f"    [X] Error reading {filepath}: {e}")
        return 0
    except Exception as e:
        # Re-raise so the caller can detect partial-migration failures and
        # avoid deleting the source JSON file when --delete-json is on.
        # A bare `return 0` here used to make a half-migrated file
        # indistinguishable from an empty file → eligible for deletion.
        print(f"    [X] Migration aborted for {filepath} after partial write: {e}")
        raise


async def migrate_metadata(channel_id: int, filepath: Path, dry_run: bool = False) -> bool:
    """Migrate a single metadata file to database."""
    try:
        metadata = json.loads(filepath.read_text(encoding="utf-8"))

        if not isinstance(metadata, dict):
            return False

        thinking_enabled = metadata.get("thinking_enabled", True)

        if not dry_run:
            await db.save_ai_metadata(channel_id=channel_id, thinking_enabled=thinking_enabled)

        return True

    except (json.JSONDecodeError, OSError) as e:
        print(f"    [X] Error reading {filepath}: {e}")
        return False


def create_backup() -> Path | None:
    """Create a backup of the data directory."""
    # Anchor to the project root rather than the CWD so the backup lands next
    # to the real data/ dir even if create_backup() is ever called before
    # async_main()'s os.chdir(PROJECT_ROOT).
    _root = Path(__file__).resolve().parents[2]
    data_dir = _root / "data"
    if not data_dir.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = _root / f"data_backup_{timestamp}"

    shutil.copytree(data_dir, backup_dir)
    return backup_dir


async def async_main():
    """Main migration function."""
    parser = argparse.ArgumentParser(description="Migrate JSON files to SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    parser.add_argument("--backup", action="store_true", help="Create backup before migration")
    parser.add_argument(
        "--delete-json", action="store_true", help="Delete JSON files after successful migration"
    )
    parser.add_argument(
        "--yes-delete-json",
        action="store_true",
        help=(
            "Acknowledge JSON deletion without --backup. Required by --delete-json "
            "when --backup is not given (safety guard)."
        ),
    )
    args = parser.parse_args()

    # Safety: refuse to delete the source JSON unless the user has either
    # taken a backup OR explicitly acknowledged with --yes-delete-json.
    # The migration writes to a NEW SQLite file; if anything corrupts the
    # database between now and the next bot start, the deleted JSON is the
    # only copy of the user's history. Make this require a deliberate signal.
    if args.delete_json and not args.dry_run and not args.backup and not args.yes_delete_json:
        print(
            "[ABORT] --delete-json refused: pass --backup to snapshot the data "
            "first, or --yes-delete-json to acknowledge that you accept the risk "
            "of losing the source files."
        )
        sys.exit(2)

    # CLI entry point: chdir to project root so relative paths resolve.
    os.chdir(PROJECT_ROOT)

    # Initialize database before use — but skip during dry run so the
    # schema migrations don't get applied when the user explicitly asked
    # for "no changes".
    if not args.dry_run:
        await db.init_schema()
    else:
        print("  [DRY RUN] Skipping db.init_schema() — no schema changes will be applied.")

    try:
        await _run_migration(args)
    finally:
        # The pool's aiosqlite connections run on NON-daemon threads; without
        # an explicit close the interpreter blocks forever in
        # threading._shutdown() and the script hangs at exit
        # (mirrors schema_smoke.py).
        await db.stop_background_tasks()
        await db.close_pool()


async def _run_migration(args) -> None:
    """Body of the migration (separated so async_main can guarantee pool close)."""

    print()
    print("=" * 60)
    print("  📦 JSON to SQLite Migration Tool")
    print("=" * 60)
    print()

    if args.dry_run:
        print("  [MODE] Dry Run - No changes will be made")
        print()

    # Find files to migrate
    print("  [1/4] Scanning for JSON files...")
    files = find_json_files()

    total_history = len(files["history"])
    total_metadata = len(files["metadata"])
    total_queue = len(files["queue"])

    print(f"        Found {total_history} history files")
    print(f"        Found {total_metadata} metadata files")
    if total_queue:
        # This tool does not migrate queue files — the music cog loads
        # queue_*.json into the music_queue table on the next bot start.
        # Say so explicitly so the count below isn't mistaken for pending work.
        print(f"        Found {total_queue} queue files (handled by the bot at startup, not here)")
    print()

    if total_history == 0 and total_metadata == 0:
        if total_queue:
            print("  [OK] Nothing for this tool to migrate (queue files load on next bot start).")
        else:
            print("  [OK] No files to migrate!")
        print()
        return

    # Create backup if requested
    if args.backup and not args.dry_run:
        print("  [2/4] Creating backup...")
        backup_path = create_backup()
        if backup_path:
            print(f"        Backup created: {backup_path}")
        print()
    else:
        print("  [2/4] Skipping backup (not requested)")
        print()

    # Migrate history files
    print("  [3/4] Migrating history files...")
    migrated_messages = 0
    migrated_files = 0
    # Track files that migrated successfully — used to limit --delete-json
    # to only the files we actually imported, preventing data loss on partial failure.
    migrated_history_paths: list[Path] = []

    for channel_id, filepath in files["history"]:
        try:
            count = await migrate_history(channel_id, filepath, args.dry_run)
        except Exception:
            # Partial migration: some rows already inserted but the file
            # blew up midway. Do NOT mark this filepath migrated so the
            # cleanup step won't unlink an under-imported source.
            print(f"        ✗ Channel {channel_id}: skipped (partial failure)")
            continue
        if count > 0:
            migrated_messages += count
            migrated_files += 1
            migrated_history_paths.append(filepath)
            print(f"        ✓ Channel {channel_id}: {count} messages")

    print(f"        Total: {migrated_messages} messages from {migrated_files} files")
    print()

    # Migrate metadata files
    print("  [4/4] Migrating metadata files...")
    metadata_count = 0
    migrated_metadata_paths: list[Path] = []

    for channel_id, filepath in files["metadata"]:
        try:
            ok = await migrate_metadata(channel_id, filepath, args.dry_run)
        except Exception:
            # Mirror the history loop's resilience: a single bad metadata file
            # (e.g. a DB error or malformed metadata that escapes
            # migrate_metadata's own narrow except) must not abort the whole run
            # — that would skip the summary and the cleanup accounting below.
            print(f"        ✗ Channel {channel_id}: skipped (metadata write failed)")
            continue
        if ok:
            metadata_count += 1
            migrated_metadata_paths.append(filepath)
            print(f"        ✓ Channel {channel_id}: metadata migrated")

    print(f"        Total: {metadata_count} metadata records")
    print()

    # Delete old JSON files if requested — ONLY files whose migration succeeded
    if args.delete_json and not args.dry_run and migrated_files > 0:
        print("  [CLEANUP] Deleting successfully migrated JSON files...")
        deleted = 0

        for filepath in migrated_history_paths:
            try:
                filepath.unlink()
                deleted += 1
            except OSError:
                pass

        for filepath in migrated_metadata_paths:
            with contextlib.suppress(OSError):
                filepath.unlink()

        skipped = (len(files["history"]) - len(migrated_history_paths)) + (
            len(files["metadata"]) - len(migrated_metadata_paths)
        )
        print(f"        Deleted {deleted} files")
        if skipped:
            print(f"        Skipped {skipped} files (migration did not succeed)")
        print()

    # Summary
    print("=" * 60)
    print("  ✅ Migration Complete!")
    print("=" * 60)
    print(f"  • History messages: {migrated_messages}")
    print(f"  • Metadata records: {metadata_count}")
    print("  • Database file: data/bot_database.db")
    print()

    if args.dry_run:
        print("  [NOTE] This was a dry run. Run without --dry-run to apply changes.")
        print()

    # Show database stats
    try:
        import aiosqlite

        db_path = Path("data/bot_database.db")
        if db_path.exists():
            async with aiosqlite.connect(str(db_path)) as conn:
                cur = await conn.execute("SELECT COUNT(*) FROM ai_history")
                history_count = (await cur.fetchone())[0]
                cur = await conn.execute("SELECT COUNT(*) FROM ai_metadata")
                metadata_count_db = (await cur.fetchone())[0]
                db_size_mb = db_path.stat().st_size / (1024 * 1024)
            print("  📊 Database Statistics:")
            print(f"     • AI History: {history_count} records")
            print(f"     • AI Metadata: {metadata_count_db} records")
            print(f"     • Database Size: {db_size_mb:.2f} MB")
            print()
    except Exception as e:
        print(f"  [!] Could not read database stats: {e}")
        print()


if __name__ == "__main__":
    asyncio.run(async_main())
