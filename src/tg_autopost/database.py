import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import Joke
from .utils import build_hash


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jokes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    external_id TEXT NOT NULL,
    content_hash TEXT NOT NULL UNIQUE,
    source_views INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    published_at TEXT
);
"""

CREATE_INDEX_SQL = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_jokes_content_hash ON jokes(content_hash);
"""

META_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS channel_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

REACTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    username TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT
);
"""

PENDING_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pending_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part1_hash TEXT NOT NULL,
    text TEXT NOT NULL,
    source_name TEXT NOT NULL,
    external_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

SUBMITTED_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS submitted_jokes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    author_id INTEGER NOT NULL,
    author_username TEXT,
    author_name TEXT,
    submitted_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    moderator_message_id INTEGER,
    published_at TEXT
);
"""


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(CREATE_TABLE_SQL)
            connection.execute(CREATE_INDEX_SQL)
            connection.execute(PENDING_TABLE_SQL)
            connection.execute(SUBMITTED_TABLE_SQL)
            connection.execute(META_TABLE_SQL)
            connection.execute(REACTIONS_TABLE_SQL)
            self._migrate(connection)

    def _migrate(self, connection: sqlite3.Connection) -> None:
        cols = [row[1] for row in connection.execute("PRAGMA table_info(jokes)").fetchall()]
        if "source_views" not in cols:
            connection.execute("ALTER TABLE jokes ADD COLUMN source_views INTEGER NOT NULL DEFAULT 0")

    def insert_joke(self, joke: Joke) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO jokes (text, source_name, source_url, external_id, content_hash, source_views, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (joke.text, joke.source_name, joke.source_url, joke.external_id, joke.content_hash, joke.source_views, now),
            )
            return cursor.rowcount > 0

    def get_next_unpublished(self) -> Joke | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT text, source_name, source_url, external_id, content_hash, source_views, created_at, published_at
                FROM jokes
                WHERE published_at IS NULL
                ORDER BY RANDOM()
                LIMIT 1
                """
            ).fetchone()

        if row is None:
            return None

        return Joke(
            text=row["text"],
            source_name=row["source_name"],
            source_url=row["source_url"],
            external_id=row["external_id"],
            content_hash=row["content_hash"],
            source_views=row["source_views"],
            created_at=datetime.fromisoformat(row["created_at"]),
            published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
        )

    def get_next_popular_unpublished(self) -> Joke | None:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT text, source_name, source_url, external_id, content_hash, source_views, created_at, published_at
                FROM jokes
                WHERE published_at IS NULL AND source_views > 0
                ORDER BY source_views DESC, RANDOM()
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return Joke(
            text=row["text"],
            source_name=row["source_name"],
            source_url=row["source_url"],
            external_id=row["external_id"],
            content_hash=row["content_hash"],
            source_views=row["source_views"],
        )

    def get_next_unpublished_matching(self, keywords: list[str], max_batch: int = 200) -> Joke | None:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT text, source_name, source_url, external_id, content_hash, source_views
                FROM jokes
                WHERE published_at IS NULL
                ORDER BY source_views DESC, RANDOM()
                LIMIT ?
                """,
                (max_batch,),
            ).fetchall()

        for row in rows:
            text_lower = row["text"].lower()
            if not keywords or any(kw.lower() in text_lower for kw in keywords):
                return Joke(
                    text=row["text"],
                    source_name=row["source_name"],
                    source_url=row["source_url"],
                    external_id=row["external_id"],
                    content_hash=row["content_hash"],
                    source_views=row["source_views"],
                )
        return None

    def mark_published(self, content_hash: str) -> None:
        published_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "UPDATE jokes SET published_at = ? WHERE content_hash = ?",
                (published_at, content_hash),
            )

    def dedup_unpublished(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        removed = 0
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT content_hash, text FROM jokes WHERE published_at IS NULL ORDER BY created_at"
            ).fetchall()
            seen: set[str] = set()
            for row in rows:
                key = build_hash(row["text"])
                if key in seen:
                    connection.execute("UPDATE jokes SET published_at = ? WHERE content_hash = ?", (now, row["content_hash"]))
                    removed += 1
                else:
                    seen.add(key)
        return removed

    def count_unpublished(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM jokes WHERE published_at IS NULL"
            ).fetchone()
            return int(row["count"])

    def count_published(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM jokes WHERE published_at IS NOT NULL"
            ).fetchone()
            return int(row["count"])

    def count_published_today(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM jokes WHERE published_at LIKE ?",
                (today + "%",),
            ).fetchone()
            return int(row["count"])

    def get_recent_published(self, limit: int = 3, days: int = 7) -> list[Joke]:
        cutoff = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT text, source_name, source_url, external_id, content_hash, source_views
                FROM jokes
                WHERE published_at IS NOT NULL
                ORDER BY source_views DESC
                LIMIT ?
                """,
                (limit * 3,),
            ).fetchall()
        seen = set()
        result = []
        for row in rows:
            text = row["text"]
            if text not in seen:
                seen.add(text)
                result.append(Joke(
                    text=text,
                    source_name=row["source_name"],
                    source_url=row["source_url"],
                    external_id=row["external_id"],
                    content_hash=row["content_hash"],
                    source_views=row["source_views"],
                ))
            if len(result) >= limit:
                break
        return result

    def save_pending_part(self, part1_hash: str, text: str, source_name: str, external_id: str, content_hash: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO pending_parts (part1_hash, text, source_name, external_id, content_hash, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (part1_hash, text, source_name, external_id, content_hash, now),
            )

    def get_pending_part(self) -> Joke | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT text, source_name, external_id, content_hash FROM pending_parts ORDER BY created_at LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return Joke(
            text=row["text"],
            source_name=row["source_name"],
            source_url="",
            external_id=row["external_id"] + "_part2",
            content_hash=row["content_hash"],
        )

    def delete_pending_part(self, content_hash: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM pending_parts WHERE content_hash = ?", (content_hash,))

    def save_submitted_joke(self, text: str, author_id: int, author_username: str | None, author_name: str | None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO submitted_jokes (text, author_id, author_username, author_name, submitted_at, status) VALUES (?, ?, ?, ?, ?, 'pending')",
                (text, author_id, author_username, author_name, now),
            )
            return int(cursor.lastrowid)

    def get_pending_submissions(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, text, author_id, author_username, author_name, submitted_at FROM submitted_jokes WHERE status = 'pending' ORDER BY submitted_at"
            ).fetchall()
            return [dict(r) for r in rows]

    def set_moderator_message(self, joke_id: int, message_id: int) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE submitted_jokes SET moderator_message_id = ? WHERE id = ?",
                (message_id, joke_id),
            )

    def approve_submission(self, joke_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE submitted_jokes SET status = 'approved' WHERE id = ? AND status = 'pending'",
                (joke_id,),
            )
            return cursor.rowcount > 0

    def reject_submission(self, joke_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE submitted_jokes SET status = 'rejected' WHERE id = ? AND status = 'pending'",
                (joke_id,),
            )
            return cursor.rowcount > 0

    def get_next_approved_submission(self) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, text, author_id, author_username, author_name FROM submitted_jokes WHERE status = 'approved' AND published_at IS NULL ORDER BY submitted_at LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def mark_submission_published(self, joke_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "UPDATE submitted_jokes SET published_at = ? WHERE id = ?",
                (now, joke_id),
            )

    def save_reaction(self, text: str, user_id: int, username: str | None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO reactions (text, user_id, username, created_at) VALUES (?, ?, ?, ?)",
                (text, user_id, username, now),
            )

    def get_random_unpublished_reaction(self) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, text, username FROM reactions WHERE published_at IS NULL ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def mark_reaction_published(self, reaction_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "UPDATE reactions SET published_at = ? WHERE id = ?", (now, reaction_id)
            )

    def count_unpublished_reactions(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM reactions WHERE published_at IS NULL"
            ).fetchone()
            return int(row["count"])

    def get_submission_author(self, joke_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT author_id, author_username, author_name FROM submitted_jokes WHERE id = ?",
                (joke_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_meta(self, key: str, default: str = "") -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM channel_meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO channel_meta (key, value) VALUES (?, ?)", (key, value)
            )

    def count_approved_submissions(self) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM submitted_jokes WHERE status = 'approved' AND published_at IS NULL"
            ).fetchone()
            return int(row["count"])
