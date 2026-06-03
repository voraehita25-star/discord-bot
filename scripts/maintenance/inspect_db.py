import sqlite3
from contextlib import closing
from pathlib import Path

# Anchor to project root so the script works no matter what cwd it's
# launched from. Otherwise sqlite3.connect would silently CREATE a new
# empty DB next to the current dir and report "0 tables".
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

for db in ["data/bot_database.db", "data/ai_cache_l2.db"]:
    db_path = _PROJECT_ROOT / db
    try:
        # closing() guarantees the connection is closed: sqlite3's own context
        # manager only commits/rolls back the transaction, it does NOT close the
        # connection, so each loop iteration would otherwise leak one handle.
        with closing(sqlite3.connect(db_path)) as conn:
            print(f"==== {db_path} ====")
            for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
                print(f"-- Table: {row[0]}\n{row[1]}\n")
    except Exception as e:
        print(f"Skipping {db_path}: {e}")
