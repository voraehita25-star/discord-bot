import sqlite3

for db in ['data/bot_database.db', 'data/ai_cache_l2.db']:
    try:
        with sqlite3.connect(db) as conn:
            print(f'==== {db} ====')
            for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type='table'"):
                print(f'-- Table: {row[0]}\n{row[1]}\n')
    except Exception as e:
        print(f'Skipping {db}: {e}')
