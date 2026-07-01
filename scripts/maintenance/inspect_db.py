import sqlite3
from contextlib import closing
from pathlib import Path

# Anchor to project root so the script inspects the real DB no matter
# what cwd it is launched from. Silent creation of an empty DB is
# prevented by mode=ro on connect (below), not by anchoring.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

for db in ["data/bot_database.db", "data/ai_cache_l2.db"]:
    db_path = _PROJECT_ROOT / db
    try:
        # closing() guarantees the connection is closed: sqlite3's own context
        # manager only commits/rolls back the transaction, it does NOT close the
        # connection, so each loop iteration would otherwise leak one handle.
        # mode=ro: read-only schema dump - never create the DB or its -wal/-shm
        # sidecars. A missing file raises OperationalError, caught below and
        # reported as "Skipping ..." instead of leaving a stray empty .db behind.
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
            print(f"==== {db_path} ====")
            for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
                print(f"-- Table: {row[0]}\n{row[1]}\n")
    except Exception as e:
        print(f"Skipping {db_path}: {e}")
