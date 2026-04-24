"""
Migration Script: JSON to SQLite Database
Converts existing JSON history files to the new SQLite database.

Usage:
    python scripts/migrate_to_db.py
    python scripts/migrate_to_db.py --dry-run  # Preview without changes
    python scripts/migrate_to_db.py --backup   # Create backup before migration
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

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import contextlib

from utils.database import db

JsonFileGroup = list[tuple[int, Path]]
JsonFileBuckets = dict[str, JsonFileGroup]


def find_json_files() -> JsonFileBuckets:
    """Find all JSON files that need to be migrated."""
    data_dir = Path("data")
    config_dir = Path("data/ai_config")

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
    """Migrate a single history file to database."""
    try:
        history = json.loads(filepath.read_text(encoding="utf-8"))  # noqa: ASYNC240 - one-shot CLI migration

        if not isinstance(history, list):
            print(f"    [!] Invalid format in {filepath}")
            return 0

        count = 0
        for item in history:
            if not isinstance(item, dict):
                continue

            role = item.get("role", "user")
            parts = item.get("parts", [])
            message_id = item.get("message_id")
            timestamp = item.get("timestamp")

            # Convert parts to string (handle both str and dict formats)
            if isinstance(parts, list):
                def _extract_text(part: Any) -> str:
                    if isinstance(part, str):
                        return part
                    if isinstance(part, dict) and "text" in part:
                        text = part["text"]
                        return text if isinstance(text, str) else str(text)
                    return str(part)
                content = "\n".join(_extract_text(p) for p in parts if p)
            else:
                content = str(parts)

            if not content:
                continue

            if not dry_run:
                await db.save_ai_message(
                    channel_id=channel_id,
                    role=role,
                    content=content,
                    message_id=message_id,
                    timestamp=timestamp,
                )
            count += 1

        return count

    except (json.JSONDecodeError, OSError) as e:
        print(f"    [X] Error reading {filepath}: {e}")
        return 0


async def migrate_metadata(channel_id: int, filepath: Path, dry_run: bool = False) -> bool:
    """Migrate a single metadata file to database."""
    try:
        metadata = json.loads(filepath.read_text(encoding="utf-8"))  # noqa: ASYNC240 - one-shot CLI migration

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
    data_dir = Path("data")
    if not data_dir.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(f"data_backup_{timestamp}")

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
    args = parser.parse_args()

    # Initialize database before use
    await db.init_schema()

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
    print(f"        Found {total_queue} queue files")
    print()

    if total_history == 0 and total_metadata == 0:
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
        count = await migrate_history(channel_id, filepath, args.dry_run)
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
        if await migrate_metadata(channel_id, filepath, args.dry_run):
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
        if db_path.exists():  # noqa: ASYNC240 - one-shot CLI migration
            async with aiosqlite.connect(str(db_path)) as conn:
                cur = await conn.execute("SELECT COUNT(*) FROM ai_history")
                history_count = (await cur.fetchone())[0]
                cur = await conn.execute("SELECT COUNT(*) FROM ai_metadata")
                metadata_count_db = (await cur.fetchone())[0]
                db_size_mb = db_path.stat().st_size / (1024 * 1024)  # noqa: ASYNC240
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
