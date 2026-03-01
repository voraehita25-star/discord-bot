import json
import sqlite3

try:
    conn = sqlite3.connect('data/bot_database.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    tables = cursor.fetchall()

    schema = {}
    for name, sql in tables:
        schema[name] = sql

    print(json.dumps(schema, indent=2))
except Exception as e:
    print(f"Error: {e}")
finally:
    if 'conn' in locals():
        conn.close()
