"""Create shorts_candidates table if missing and seed candidates."""
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB = Path("data/jokes.db")
if not DB.exists():
    print("No DB found")
    exit(0)

SHORTS_SQL = """CREATE TABLE IF NOT EXISTS shorts_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'battle',
    created_at TEXT NOT NULL
);"""

conn = sqlite3.connect(str(DB))
conn.execute(SHORTS_SQL)
conn.commit()

cnt = conn.execute("SELECT COUNT(*) FROM shorts_candidates").fetchone()[0]
target = 5
if cnt >= target:
    print(f"Already {cnt} candidates (need >= {target})")
    conn.close()
    exit(0)

jokes = conn.execute("SELECT text FROM jokes ORDER BY RANDOM() LIMIT ?", (target - cnt,)).fetchall()
now = datetime.now(timezone.utc).isoformat()
added = 0
for joke in jokes:
    conn.execute(
        "INSERT INTO shorts_candidates (text, source, created_at) VALUES (?, ?, ?)",
        (joke[0], "seed", now),
    )
    added += 1
conn.commit()
print(f"Added {added} candidates (total: {conn.execute('SELECT COUNT(*) FROM shorts_candidates').fetchone()[0]})")
conn.close()
