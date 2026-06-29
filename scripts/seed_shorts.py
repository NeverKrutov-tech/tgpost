"""Create shorts_candidates table if missing and seed one candidate."""
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
if cnt > 0:
    print(f"Already {cnt} candidates")
    conn.close()
    exit(0)

joke = conn.execute("SELECT text FROM jokes ORDER BY RANDOM() LIMIT 1").fetchone()
if not joke:
    print("No jokes in DB")
    conn.close()
    exit(0)

conn.execute(
    "INSERT INTO shorts_candidates (text, source, created_at) VALUES (?, ?, ?)",
    (joke[0], "seed", datetime.now(timezone.utc).isoformat()),
)
conn.commit()
print(f"Seeded: {joke[0][:80]}...")
conn.close()
