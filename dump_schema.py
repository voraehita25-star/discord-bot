import sqlite3


def dump_schema(db_path):
    print(f"\n--- {db_path} ---")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        if not tables:
            print("No tables found.")
        for name, sql in tables:
            print(f"Table: {name}")
            print(f"{sql}\n")
        conn.close()
    except Exception as e:
        print(f"Error reading {db_path}: {e}")


if __name__ == "__main__":
    dump_schema("data/bot_database.db")
    dump_schema("data/ai_cache_l2.db")
