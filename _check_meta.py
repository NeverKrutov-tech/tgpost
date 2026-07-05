import sqlite3
c = sqlite3.connect("data/jokes.db")
c.row_factory = sqlite3.Row
rows = c.execute("SELECT key, value FROM channel_meta").fetchall()
for r in rows:
    print(f"{r['key']} = {r['value']}")
print("---")
rows2 = c.execute("SELECT id, text, source FROM shorts_candidates ORDER BY id DESC LIMIT 5").fetchall()
for r in rows2:
    print(f"#{r['id']} | {r['source']:10s} | {r['text'][:60]}")
c.close()
