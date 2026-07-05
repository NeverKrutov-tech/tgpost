import sqlite3, sys
c = sqlite3.connect("data/jokes.db")
c.row_factory = sqlite3.Row

print("=== Last 5 published ===")
rows = c.execute("SELECT text, published_at FROM jokes WHERE published_at IS NOT NULL ORDER BY published_at DESC LIMIT 5").fetchall()
for r in rows:
    print(f"{r['published_at'][:19]} | {r['text'][:80]}")

print("\n=== Shorts candidates ===")
rows = c.execute("SELECT id, text, source FROM shorts_candidates ORDER BY id DESC LIMIT 5").fetchall()
for r in rows:
    print(f"#{r['id']} | {r['source']:10s} | {r['text'][:60]}")

print("\n=== Channel meta keys ===")
rows = c.execute("SELECT key, value FROM channel_meta ORDER BY key").fetchall()
for r in rows:
    print(f"{r['key']} = {r['value']}")

print(f"\nUnpublished jokes: {c.execute('SELECT COUNT(*) FROM jokes WHERE published_at IS NULL').fetchone()[0]}")
print(f"Total jokes: {c.execute('SELECT COUNT(*) FROM jokes').fetchone()[0]}")
c.close()
