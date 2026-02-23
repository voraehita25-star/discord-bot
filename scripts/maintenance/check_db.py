import asyncio

import aiosqlite


async def check():
    async with aiosqlite.connect("data/bot_database.db") as conn:
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
