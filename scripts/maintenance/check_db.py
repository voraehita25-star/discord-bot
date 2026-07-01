import asyncio
from pathlib import Path

import aiosqlite

# Anchor to project root so a different cwd still resolves to the real DB.
# Anchoring only fixes the cwd, though; the ?mode=ro open below is what actually
# prevents silently creating a stray empty DB when the file is missing.
_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "bot_database.db"


async def check() -> None:
    if not _DB_PATH.exists():
        print(f"Database not found: {_DB_PATH}")
        print("Run the bot at least once so it creates data/bot_database.db.")
        raise SystemExit(1)
    # mode=ro: read-only inspection (SELECT only), so never create/checkpoint the
    # DB or its -wal/-shm sidecars (mirrors view_db.py / watch_history.py). uri=True
    # forwards through aiosqlite to sqlite3.connect, which accepts the native path
    # (backslashes + the space in the repo dir) verbatim in the URI filename.
    async with aiosqlite.connect(f"file:{_DB_PATH}?mode=ro", uri=True) as conn:
        conn.row_factory = aiosqlite.Row
        cur = await conn.execute("""
            SELECT channel_id, MIN(id) as min_id, MAX(id) as max_id, COUNT(*) as count
            FROM ai_history
            GROUP BY channel_id
            ORDER BY min_id
        """)
        rows = await cur.fetchall()
        print("Channel ID           | Min ID | Max ID | Count")
        print("-" * 55)
        for r in rows:
            print(f"{r['channel_id']} | {r['min_id']:6} | {r['max_id']:6} | {r['count']}")


if __name__ == "__main__":
    asyncio.run(check())
