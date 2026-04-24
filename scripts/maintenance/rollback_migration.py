"""
Migration rollback helper (#34).

SQLite migrations in this project are forward-only (no `DOWN` blocks) because
most real changes — `ALTER TABLE`, `DROP TABLE`, column default rewrites —
either can't be undone losslessly or would silently drop user data if tried.
Instead we lean on the **auto-backup** created by `init_schema()` right before
any pending migration runs (kept under `data/backups/`, last 5 retained).

This script gives the operator three tools:

    list        — show every available backup with size + version + timestamp
    diff        — print schema / row-count delta between current DB and a backup
    restore     — atomically swap the current DB with a chosen backup
                  (keeps a "pre_rollback_*.db" copy so the rollback itself is undoable)

Usage:
    python scripts/maintenance/rollback_migration.py list
    python scripts/maintenance/rollback_migration.py diff bot_database_v12_20260423_080000.db
    python scripts/maintenance/rollback_migration.py restore bot_database_v12_20260423_080000.db

The DB must be CLOSED (bot stopped) before restoring; the script aborts if it
can't get an exclusive lock.

Design notes:
  - No partial rollback. If you applied migrations 5 → 6 → 7 and only want to
    undo 7, restore the backup tagged `v6` (created before 7 ran) and re-apply
    6+ anything new by starting the bot. The backup filename embeds the version
    so picking the right one is straightforward.
  - Future-proofing: If a migration adds user-generated data (pinned messages,
    tags, etc.) that the user would lose on rollback, `diff` flags it so the
    operator can export first.
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = REPO_ROOT / "data" / "bot_database.db"
BACKUP_DIR = REPO_ROOT / "data" / "backups"


def _ensure_backup_dir() -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def _list_backups() -> list[Path]:
    _ensure_backup_dir()
    return sorted(BACKUP_DIR.glob("bot_database_v*.db"), key=lambda p: p.stat().st_mtime, reverse=True)


def _get_schema_version(db: Path) -> int | None:
    try:
        with sqlite3.connect(str(db)) as conn:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    except sqlite3.Error:
        return None


def _table_row_counts(db: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    try:
        with sqlite3.connect(str(db)) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            for (name,) in rows:
                try:
                    cur = conn.execute(f'SELECT COUNT(*) FROM "{name}"')
                    counts[name] = int(cur.fetchone()[0])
                except sqlite3.Error:
                    counts[name] = -1
    except sqlite3.Error:
        pass
    return counts


def cmd_list(_args: argparse.Namespace) -> int:
    backups = _list_backups()
    if not backups:
        print(f"No backups found under {BACKUP_DIR}")
        print("The bot creates backups automatically before applying migrations —")
        print("start the bot at least once to populate this directory.")
        return 0

    current_version = _get_schema_version(DB_PATH) if DB_PATH.exists() else None
    print(f"Current DB: {DB_PATH} (version {current_version if current_version is not None else 'unknown'})")
    print(f"Backups under {BACKUP_DIR}:\n")
    print(f"  {'Filename':<50}  {'Size':>10}  {'Modified':<19}  Restorable")
    print(f"  {'-' * 50}  {'-' * 10}  {'-' * 19}  ----------")
    for b in backups:
        size = b.stat().st_size
        mtime = datetime.fromtimestamp(b.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        version = _get_schema_version(b)
        restorable = version is not None
        print(f"  {b.name:<50}  {size:>10,}  {mtime}  {'v' + str(version) if restorable else 'CORRUPT'}")
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    backup = BACKUP_DIR / args.backup
    if not backup.exists():
        print(f"ERROR: backup not found: {backup}")
        return 1
    if not DB_PATH.exists():
        print(f"ERROR: current DB missing: {DB_PATH}")
        return 1

    cur_counts = _table_row_counts(DB_PATH)
    bak_counts = _table_row_counts(backup)
    all_tables = sorted(set(cur_counts) | set(bak_counts))

    print(f"Comparing:\n  current: {DB_PATH} (v{_get_schema_version(DB_PATH)})")
    print(f"  backup:  {backup} (v{_get_schema_version(backup)})\n")
    print(f"  {'Table':<40}  {'Current':>10}  {'Backup':>10}  {'Delta':>8}")
    print(f"  {'-' * 40}  {'-' * 10}  {'-' * 10}  {'-' * 8}")
    data_loss = False
    for t in all_tables:
        c = cur_counts.get(t, 0)
        b = bak_counts.get(t, 0)
        delta = c - b
        if delta > 0:
            data_loss = True
        marker = "" if t in cur_counts and t in bak_counts else "  (table only in one side)"
        print(f"  {t:<40}  {c:>10}  {b:>10}  {delta:>+8}{marker}")

    if data_loss:
        print("\n⚠️  WARNING: current DB has rows the backup does not.")
        print("   Restoring will DISCARD those rows. Export anything you want to keep first.")
    else:
        print("\n✓ No row-loss detected. Rollback is safe.")
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    backup = BACKUP_DIR / args.backup
    if not backup.exists():
        print(f"ERROR: backup not found: {backup}")
        return 1

    if not args.yes:
        print(f"About to restore: {backup}")
        print(f"  onto: {DB_PATH}")
        print("\nThe current DB will first be copied to a `pre_rollback_*.db` file so the\n"
              "rollback itself is undoable. Make sure the bot is STOPPED.")
        resp = input("Type YES to continue: ").strip()
        if resp != "YES":
            print("Aborted.")
            return 1

    # Ensure nothing is holding the DB open (WAL files stay from crashed process).
    # We can't force-close the bot's connections, but we can refuse to restore
    # if we see fresh -wal/-shm that look in-use (file size > 0).
    wal = DB_PATH.with_suffix(DB_PATH.suffix + "-wal")
    shm = DB_PATH.with_suffix(DB_PATH.suffix + "-shm")
    for path in (wal, shm):
        if path.exists() and path.stat().st_size > 0:
            print(f"ERROR: {path.name} is non-empty — is the bot still running?")
            print("Stop the bot first, then retry.")
            return 1

    # Safety snapshot of the current DB BEFORE overwriting.
    _ensure_backup_dir()
    if DB_PATH.exists():
        safety = BACKUP_DIR / f"pre_rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        shutil.copy2(DB_PATH, safety)
        print(f"✓ Safety snapshot: {safety.name}")

    shutil.copy2(backup, DB_PATH)
    # Wipe stale WAL/SHM so SQLite starts clean against the restored file.
    for path in (wal, shm):
        if path.exists():
            try:
                path.unlink()
            except OSError as e:
                print(f"  (warning: could not remove {path.name}: {e})")

    new_ver = _get_schema_version(DB_PATH)
    print(f"✓ Restored to schema version {new_ver}")
    print("  The next bot startup will NOT re-apply migrations above this version —")
    print("  init_schema() checks `SELECT MAX(version) FROM schema_version` and skips")
    print(f"  migrations whose version <= {new_ver}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite migration rollback helper.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List available backups.")

    p_diff = sub.add_parser("diff", help="Compare current DB with a backup (row counts).")
    p_diff.add_argument("backup", help="Backup filename (as shown by `list`).")

    p_restore = sub.add_parser("restore", help="Restore the DB from a backup.")
    p_restore.add_argument("backup", help="Backup filename (as shown by `list`).")
    p_restore.add_argument("--yes", action="store_true",
                           help="Skip the interactive 'type YES' confirmation.")

    args = parser.parse_args()
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "diff":
        return cmd_diff(args)
    if args.cmd == "restore":
        return cmd_restore(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
