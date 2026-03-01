import json
import sqlite3

conn = sqlite3.connect('data/bot_database.db')
cursor = conn.cursor()
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()

schema = dict(tables)
with open('db_schema_clean.json', 'w', encoding='utf-8') as f:
    json.dump(schema, f, indent=2)
