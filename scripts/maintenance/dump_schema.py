import json
import sqlite3
from pathlib import Path


def get_schema(db_path):
    path = Path(db_path)
    if not path.exists():
        return {"error": "File not found"}
    try:
        # Use URI with mode=ro to avoid any locking conflicts with the running bot
        abs_path = str(path.resolve()).replace("\\", "/")
        conn = sqlite3.connect(f"file:{abs_path}?mode=ro", uri=True, timeout=5)
        cur = conn.cursor()
        tables = [
            r[0]
            for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        schema = {}
        for t in tables:
            columns = cur.execute(f"PRAGMA table_info([{t}])").fetchall()
            schema[t] = [
                {
                    "cid": c[0],
                    "name": c[1],
                    "type": c[2],
                    "notnull": c[3],
                    "dflt_value": c[4],
                    "pk": c[5],
                }
                for c in columns
            ]
        conn.close()
        return schema
    except Exception as e:
        return {"error": str(e)}


def main():
    Path("temp").mkdir(parents=True, exist_ok=True)
    output = {
        "bot_database.db": get_schema("data/bot_database.db"),
        "ai_cache_l2.db": get_schema("data/ai_cache_l2.db"),
        "bot.db": get_schema("data/bot.db"),
    }

    output_path = Path("temp/schema_dump.json")
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"SUCCESS: Schema completely extracted to {output_path}")


if __name__ == "__main__":
    main()
