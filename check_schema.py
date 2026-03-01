import os
import re
import sqlite3

# Connect to DB and get schema
conn = sqlite3.connect('data/bot_database.db')
cursor = conn.cursor()
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
db_tables = {row[0]: row[1] for row in cursor.fetchall() if not row[0].startswith('sqlite_')}

# Scan Python files for CREATE TABLE
python_tables = {}
for root, _, files in os.walk('.'):
    if '.venv' in root or 'tests' in root or 'node_modules' in root or '.git' in root:
        continue
    for file in files:
        if file.endswith('.py') and file != 'check_schema.py':
            filepath = os.path.join(root, file)
            try:
                with open(filepath, encoding='utf-8') as f:
                    content = f.read()
                    matches = re.finditer(r'CREATE TABLE\s+(?:IF NOT EXISTS\s+)?([a-zA-Z_0-9"]+)\s*\((.*?)\)', content, re.DOTALL | re.IGNORECASE)
                    for match in matches:
                        table_name = match.group(1).replace('"', '').strip()
                        schema = match.group(2).strip()
                        python_tables[table_name] = (filepath, schema)
            except Exception:
                pass

print('=== DB vs Code Schema Mismatches ===')
for table, sql in db_tables.items():
    if table not in python_tables:
        print(f'WARNING: Table {table} found in DB but no CREATE TABLE found in Python code.')
    else:
        print(f'OK: Table {table} matches in DB and code ({python_tables[table][0]}).')

for table, (filepath, _) in python_tables.items():
    if table not in db_tables:
        print(f'WARNING: Table {table} defined in {filepath} but not found in DB.')

# Check for specific expected columns
expected_columns = {
    'dashboard_messages': ['thinking', 'mode'],
    'dashboard_user_profile': ['is_creator'],
    'ai_history': ['local_id', 'user_id']
}

print('\n=== Column Checks ===')
for table, cols in expected_columns.items():
    if table in db_tables:
        sql = db_tables[table].lower()
        for col in cols:
            if col in sql:
                print(f'OK: {table}.{col} found in DB schema')
            else:
                print(f'ERROR: {table}.{col} missing from DB schema')

