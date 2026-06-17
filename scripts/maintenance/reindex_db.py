"""
Re-index AI History IDs Script
Re-numbers all IDs in ai_history table to start from 1 sequentially.

IMPORTANT: Run this while the bot is STOPPED to avoid conflicts.
"""

import asyncio
import re
import shutil
import signal
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import aiosqlite


@contextmanager
def _ignore_sigint():
    """Temporarily ignore SIGINT for a critical commit window.

    Ctrl-C arriving between a successful ``conn.commit()`` and the
    ``commit_succeeded`` flag would race the BaseException handler into
    a ROLLBACK on an already-durable transaction — sqlite docs
    explicitly say that's undefined and can corrupt the DB.
    """
    try:
        old_handler = signal.getsignal(signal.SIGINT)
    except (ValueError, OSError):
        old_handler = None
    installed = False
    try:
        try:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            installed = True
        except (ValueError, OSError):
            # Not main thread on this platform — best-effort only.
            pass
        yield
    finally:
        # Track install success with a flag rather than inferring it from
        # old_handler: getsignal() returns None for a C-level handler, which
        # would otherwise skip restoration and leave SIGINT permanently ignored.
        if installed:
            try:
                signal.signal(signal.SIGINT, old_handler or signal.default_int_handler)
            except (ValueError, OSError):
                pass


# Anchor paths to the project root so the script works regardless of cwd
# (otherwise the destructive DROP+RENAME could target a stray empty DB
# created next to the current dir).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = str(_PROJECT_ROOT / "data" / "bot_database.db")
BACKUP_DIR = _PROJECT_ROOT / "data" / "backups"
PID_FILE = _PROJECT_ROOT / "bot.pid"


def _abort_if_bot_running() -> None:
    """Refuse to run if the bot's PID file is present.

    A live bot writing to WAL while we DROP/RENAME the table is a
    perfect recipe for corruption. The convention-only "stop the bot
    first" comment in the docstring isn't enough — make it a hard fail.
    """
    if PID_FILE.exists():
        try:
            existing_pid = PID_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            existing_pid = "<unreadable>"
        print(
            f"[ERROR] {PID_FILE} exists (pid={existing_pid}) — refusing to "
            f"re-index while the bot may be running. Stop the bot and "
            f"delete the PID file if it's stale, then retry.",
            file=sys.stderr,
        )
        sys.exit(1)


async def reindex_ai_history():
    """Re-index all IDs in ai_history table to be sequential starting from 1.

    Re-numbering primary keys is destructive: any external references to
    ``ai_history.id`` (exported JSON dumps, audit-log links, third-party
    tools that cached IDs) will silently break. The script refuses to
    run if foreign-key constraints from other tables target ai_history.
    """

    _abort_if_bot_running()

    # Fail fast with a clear message (not a raw FileNotFoundError traceback from
    # shutil.copy2 below) when the database file is missing.
    if not Path(DB_PATH).exists():
        print(f"[ERROR] Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

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

        # Enforce foreign keys for the verification PRAGMA at step 6 below.
        # SQLite defaults this OFF per connection; without it
        # ``foreign_key_check`` returns no rows even when references are
        # broken, defeating the post-rename integrity gate.
        await conn.execute("PRAGMA foreign_keys=ON")

        # Refuse to run if any other table references ai_history(id) — the
        # FK constraint would either be invalidated or silently corrupt
        # rows after the table swap. Operator must manually drop/recreate.
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'ai_history'"
        )
        other_tables = [r["name"] for r in await cursor.fetchall()]
        for tbl in other_tables:
            # ``tbl`` originates from sqlite_master so it's normally trusted,
            # but a table name containing a single quote (legal in SQLite if
            # quoted at creation time) would break the PRAGMA. Quote-escape
            # defensively; PRAGMA arguments don't accept bind parameters.
            safe_tbl = tbl.replace("'", "''")
            try:
                cursor = await conn.execute(f"PRAGMA foreign_key_list('{safe_tbl}')")
                fks = await cursor.fetchall()
            except Exception as exc:
                # Don't silently skip — a swallowed error here means a
                # real FK to ai_history could go undetected and the
                # rename would silently break referential integrity.
                print(
                    f"[ERROR] Could not read foreign keys for table {tbl!r}: "
                    f"{exc}. Aborting to avoid an undetected broken FK."
                )
                return
            for fk in fks:
                if fk["table"] == "ai_history":
                    print(
                        f"[ERROR] Refusing to run: table {tbl!r} has a "
                        f"FOREIGN KEY referencing ai_history. Renumbering "
                        f"would invalidate it."
                    )
                    return

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

        # Collect trigger and view definitions tied to ai_history so the
        # DROP TABLE below doesn't silently take them with it. SQLite drops
        # any trigger that targets a table when the table is dropped, and a
        # view that references the table becomes "schema corrupt" until
        # it's recreated. Without this, a reindex would silently delete
        # production triggers (audit logging, denormalised counters, etc.)
        # and views that operators rely on.
        cursor = await conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='trigger' AND tbl_name='ai_history' AND sql IS NOT NULL"
        )
        trigger_defs = [(r["name"], r["sql"]) for r in await cursor.fetchall()]
        # ``LIKE '%ai_history%'`` is only a coarse pre-filter — it over-matches
        # views that merely mention the substring (e.g. ai_history_archive, an
        # alias ai_history_count, or a comment) without actually referencing the
        # ai_history table. Recreating such a false-positive view is needless
        # churn and, if its recreate fails, would force a non-zero exit on an
        # otherwise-successful reindex. Tighten with a word-boundary check so
        # only views that reference ai_history as a standalone identifier are
        # carried over.
        cursor = await conn.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='view' AND sql IS NOT NULL AND sql LIKE '%ai_history%'"
        )
        _ai_history_word = re.compile(r"(?<!\w)ai_history(?!\w)", re.IGNORECASE)
        view_defs = [
            (r["name"], r["sql"])
            for r in await cursor.fetchall()
            if _ai_history_word.search(r["sql"])
        ]

        # Wrap the destructive section in an explicit transaction so an
        # interrupt between DROP TABLE ai_history and the RENAME doesn't
        # leave the DB without a real ai_history table (= permanent data loss).
        # If anything below raises, the `with` exits via exception and we
        # ROLLBACK in the except block (unless commit_failed is set).
        commit_failed = False
        # Tracks whether any index recreation failed. Surfaces as a
        # non-zero exit code at the end of the script so a silently-
        # degraded database (missing index → slow queries everywhere)
        # gets caught by CI / a calling shell script. Previously a
        # missing index just printed a [WARN] and the script exited 0.
        index_recreation_failed = False
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

            # NOTE: ``PRAGMA wal_checkpoint(TRUNCATE)`` is a no-op while a
            # transaction is open (SQLite returns busy=1 and never truncates
            # the WAL). Calling it here from inside ``BEGIN IMMEDIATE`` was
            # silently ineffective — the actual checkpoint is performed
            # AFTER commit() below.

            # Step 5: Recreate every index that existed on the original table
            print(f"[STEP] Recreating {len(index_defs)} index(es)...")
            for idx_name, idx_sql in index_defs:
                try:
                    # DROP first so re-creation is idempotent. A UNIQUE index
                    # declared inline in the CREATE TABLE is recreated
                    # automatically with the new table; if the SAME index also
                    # exists as an explicit CREATE INDEX row, executing idx_sql
                    # verbatim would raise "index already exists" and force a
                    # non-zero exit on an otherwise-successful reindex.
                    await conn.execute(f'DROP INDEX IF EXISTS "{idx_name}"')
                    await conn.execute(idx_sql)
                    print(f"  [OK] Recreated index: {idx_name}")
                except Exception as e:
                    # Promote to [ERROR] and flag for non-zero exit at end —
                    # a missing index after a reindex is a real degradation
                    # (full-table scans on the AI history hot path) and
                    # should not silently slide past CI as a warning.
                    print(f"  [ERROR] Could not recreate index {idx_name}: {e}")
                    index_recreation_failed = True

            # Step 5b: Recreate triggers (DROP TABLE cascaded them away).
            print(f"[STEP] Recreating {len(trigger_defs)} trigger(s)...")
            for trg_name, trg_sql in trigger_defs:
                try:
                    await conn.execute(trg_sql)
                    print(f"  [OK] Recreated trigger: {trg_name}")
                except Exception as e:
                    print(f"  [ERROR] Could not recreate trigger {trg_name}: {e}")
                    # Use the same exit flag so a missing trigger fails CI.
                    index_recreation_failed = True

            # Step 5c: Recreate views (sqlite_master keeps the original SQL
            # but the view becomes invalid the moment its underlying table
            # is dropped — recreate explicitly so the view definition is
            # bound against the new ai_history rowid space).
            print(f"[STEP] Recreating {len(view_defs)} view(s)...")
            for view_name, view_sql in view_defs:
                try:
                    # SQLite refuses CREATE VIEW for an existing name —
                    # DROP first so re-run is idempotent.
                    await conn.execute(f'DROP VIEW IF EXISTS "{view_name}"')
                    await conn.execute(view_sql)
                    print(f"  [OK] Recreated view: {view_name}")
                except Exception as e:
                    print(f"  [ERROR] Could not recreate view {view_name}: {e}")
                    index_recreation_failed = True

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
            # (sqlite docs explicitly say not to do it). Ignore SIGINT
            # across the commit so a Ctrl-C can't slip in between
            # ``await commit()`` returning and ``commit_failed`` being
            # set, then race the BaseException handler into a bogus
            # rollback.
            with _ignore_sigint():
                try:
                    await conn.commit()
                except Exception as commit_err:
                    # Mark the failure so the outer ``except BaseException``
                    # below knows to skip the ROLLBACK. Previously this path
                    # used ``sys.exit(1)`` which raised ``SystemExit`` — that
                    # still propagates through ``except BaseException``,
                    # triggering the very ROLLBACK the comment forbids.
                    commit_failed = True
                    print(f"[FATAL] commit() failed after DROP+RENAME: {commit_err}")
                    print(f"[FATAL] DO NOT manually rollback. Restore from {backup_path}.")
        except BaseException:
            # This catch fires for failures BEFORE commit (the only place
            # where ROLLBACK is meaningful). Post-commit failures set
            # ``commit_failed`` above and skip rollback.
            if not commit_failed:
                print("[ROLLBACK] Aborting — restoring original table from transaction log")
                try:
                    await conn.execute("ROLLBACK")
                except Exception as rollback_err:
                    # Don't swallow rollback failures silently — the
                    # operator needs to know the DB state is undefined.
                    print(
                        f"[ERROR] ROLLBACK failed: {rollback_err}. "
                        f"Database state is undefined; restore from {backup_path}."
                    )
            raise

        # Outside the try/except so it only runs on success path.
        if commit_failed:
            sys.exit(1)

        # Truncate the WAL now that the transaction is committed. Doing
        # this before commit was a silent no-op (PRAGMA returns busy=1
        # inside a transaction). Best-effort — log but don't fail the
        # migration on a checkpoint refusal.
        try:
            await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            print(f"  [WARN] wal_checkpoint(TRUNCATE) failed: {e}")

        # Verify new ID range. This runs AFTER commit (the rename is already
        # durable) and AFTER SIGINT was restored, so a Ctrl-C or aiosqlite
        # error here must NOT propagate out of the function — that would
        # suppress the [DONE] banner and trick an operator into re-running the
        # destructive DROP/RENAME or restoring from backup on a migration that
        # actually succeeded. Best-effort only, mirroring the wal_checkpoint
        # handling above.
        try:
            cursor = await conn.execute(
                "SELECT MIN(id) as min_id, MAX(id) as max_id FROM ai_history"
            )
            row = await cursor.fetchone()
            print(f"[OK] New ID range: {row['min_id']} - {row['max_id']}")
        except Exception as e:
            print(f"  [WARN] Could not read new ID range: {e}")

        # The migration is durable at this point — announce success BEFORE the
        # optional VACUUM so an interrupt or error during VACUUM (pure
        # optimization) doesn't hide the fact that the reindex completed.
        print("\n[DONE] Re-indexing complete!")
        print(f"[INFO] Backup saved at: {backup_path}")
        print("[TIP] You can now restart the bot and re-export JSON files")

    # VACUUM cannot run inside a transaction, and aiosqlite's ``isolation_level``
    # setter assigns directly on the CALLER thread (sqlite3's same-thread guard
    # then raises ``ProgrammingError``) — toggling it on the live aiosqlite
    # connection crashed the success path right after the durable commit. Run
    # VACUUM on a dedicated autocommit sqlite3 connection AFTER the aiosqlite
    # connection above is closed: the bot is stopped and the migration is already
    # committed, so a short-lived second connection is safe. VACUUM is best-effort
    # optimization — a failure (or Ctrl-C) leaves committed data fully intact, so
    # log a [WARN] rather than propagating (and never mask the exit(2) below).
    print("[STEP] Running VACUUM to optimize database...")
    try:
        vacuum_conn = sqlite3.connect(DB_PATH, isolation_level=None)
        try:
            vacuum_conn.execute("VACUUM")
        finally:
            vacuum_conn.close()
    except Exception as e:
        print(f"  [WARN] VACUUM failed (data is intact, optimization skipped): {e}")

    # Surface index-recreation failures as a non-zero exit so a calling
    # shell script or CI job notices. The data itself is intact (the
    # rename/commit succeeded), but the missing index means queries that
    # touched the old index will now scan — a real performance regression.
    if index_recreation_failed:
        print("[ERROR] One or more indexes failed to recreate — see [ERROR] lines above.")
        sys.exit(2)


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
