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
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

import contextlib

from utils.database import db


def find_json_files() -> dict:
    """Find all JSON files that need to be migrated."""
    data_dir = Path("data")
    config_dir = Path("data/ai_config")

    files = {"history": [], "metadata": [], "queue": []}

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


def migrate_history(channel_id: int, filepath: Path, dry_run: bool = False) -> int:
    """Migrate a single history file to database."""
    try:
        history = json.loads(filepath.read_text(encoding="utf-8"))

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

            # Convert parts to string
            if isinstance(parts, list):
                content = "\n".join(str(p) for p in parts if p)
            else:
                content = str(parts)

            if not content:
                continue

            if not dry_run:
                db.save_ai_message(
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


def migrate_metadata(channel_id: int, filepath: Path, dry_run: bool = False) -> bool:
    """Migrate a single metadata file to database."""
    try:
        metadata = json.loads(filepath.read_text(encoding="utf-8"))

        if not isinstance(metadata, dict):
            return False

        thinking_enabled = metadata.get("thinking_enabled", True)

        if not dry_run:
            db.save_ai_metadata(channel_id=channel_id, thinking_enabled=thinking_enabled)

        return True

    except (json.JSONDecodeError, OSError) as e:
        print(f"    [X] Error reading {filepath}: {e}")
        return False


def create_backup() -> Path:
    """Create a backup of the data directory."""
    data_dir = Path("data")
    if not data_dir.exists():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(f"data_backup_{timestamp}")

    shutil.copytree(data_dir, backup_dir)
    return backup_dir


def main():
    """Main migration function."""
    parser = argparse.ArgumentParser(description="Migrate JSON files to SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    parser.add_argument("--backup", action="store_true", help="Create backup before migration")
    parser.add_argument(
        "--delete-json", action="store_true", help="Delete JSON files after successful migration"
    )
    args = parser.parse_args()

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

    for channel_id, filepath in files["history"]:
        count = migrate_history(channel_id, filepath, args.dry_run)
        if count > 0:
            migrated_messages += count
            migrated_files += 1
            print(f"        ✓ Channel {channel_id}: {count} messages")

    print(f"        Total: {migrated_messages} messages from {migrated_files} files")
    print()

    # Migrate metadata files
    print("  [4/4] Migrating metadata files...")
    metadata_count = 0

    for channel_id, filepath in files["metadata"]:
        if migrate_metadata(channel_id, filepath, args.dry_run):
            metadata_count += 1
            print(f"        ✓ Channel {channel_id}: metadata migrated")

    print(f"        Total: {metadata_count} metadata records")
    print()

    # Delete old JSON files if requested
    if args.delete_json and not args.dry_run and migrated_files > 0:
        print("  [CLEANUP] Deleting old JSON files...")
        deleted = 0

        for _, filepath in files["history"]:
            try:
                filepath.unlink()
                deleted += 1
            except OSError:
                pass

        for _, filepath in files["metadata"]:
            with contextlib.suppress(OSError):
                filepath.unlink()

        print(f"        Deleted {deleted} files")
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
    stats = db.get_stats()
    print("  📊 Database Statistics:")
    print(f"     • AI History: {stats.get('ai_history_count', 0)} records")
    print(f"     • AI Metadata: {stats.get('ai_metadata_count', 0)} records")
    print(f"     • Database Size: {stats.get('db_size_mb', 0):.2f} MB")
    print()


if __name__ == "__main__":
    main()
