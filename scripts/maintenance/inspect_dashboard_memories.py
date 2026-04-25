"""Show what's stored in dashboard_memories — these are GLOBAL across every chat."""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parents[2] / "data" / "bot_database.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

cur = conn.execute("SELECT COUNT(*) AS n FROM dashboard_memories")
print(f"dashboard_memories rows : {cur.fetchone()['n']}")
print()

cur = conn.execute("PRAGMA table_info(dashboard_memories)")
print("Columns (note: NO conversation_id — table is global):")
for r in cur.fetchall():
    print(f"  {r['name']:20s}  {r['type']}")
print()

cur = conn.execute(
    """SELECT id, category, importance, substr(content, 1, 120) AS preview, created_at
       FROM dashboard_memories
       ORDER BY importance DESC, created_at DESC
       LIMIT 30"""
)
rows = cur.fetchall()
if not rows:
    print("(no memories saved)")
else:
    print(f"Top {len(rows)} memories (highest importance first — what gets injected each turn):")
    for r in rows:
        prev = r["preview"].replace("\n", " ")
        print(f"  #{r['id']:4d}  [{r['category']:15s}] imp={r['importance']}  {prev}")

print()
print("=" * 72)
print("Document memories (per-conversation):")
cur = conn.execute(
    """SELECT conversation_id, COUNT(*) AS n, SUM(LENGTH(extracted_text)) AS bytes
       FROM dashboard_document_memories
       GROUP BY conversation_id"""
)
for r in cur.fetchall():
    print(f"  conv={r['conversation_id'][:8]}…  files={r['n']}  bytes={r['bytes']}")
