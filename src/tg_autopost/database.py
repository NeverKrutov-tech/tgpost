from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from urllib.parse import urlparse

import sqlite3

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # pragma: no cover
    psycopg2 = None

from .models import Joke
from .utils import dedup_key


SQLITE_SCHEMA = [
    """
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
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_jokes_content_hash ON jokes(content_hash)",
    """
    CREATE TABLE IF NOT EXISTS channel_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        username TEXT,
        created_at TEXT NOT NULL,
        published_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_parts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        part1_hash TEXT NOT NULL,
        text TEXT NOT NULL,
        source_name TEXT NOT NULL,
        external_id TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        part1_msg_id INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    """
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
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tips (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        submission_id INTEGER NOT NULL,
        author_id INTEGER NOT NULL,
        amount INTEGER NOT NULL,
        payer_id INTEGER,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shorts_candidates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        text TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'battle',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS locked_content (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        joke_hash TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS authors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER UNIQUE NOT NULL,
        username TEXT,
        name TEXT NOT NULL,
        bio TEXT DEFAULT '',
        registered_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_quiz (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        truncated_text TEXT NOT NULL,
        full_text TEXT NOT NULL,
        answer TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
]

POSTGRES_SCHEMA = [
    """
    CREATE TABLE IF NOT EXISTS jokes (
        id BIGSERIAL PRIMARY KEY,
        text TEXT NOT NULL,
        source_name TEXT NOT NULL,
        source_url TEXT NOT NULL,
        external_id TEXT NOT NULL,
        content_hash TEXT NOT NULL UNIQUE,
        source_views INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        published_at TEXT
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_jokes_content_hash ON jokes(content_hash)",
    """
    CREATE TABLE IF NOT EXISTS channel_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reactions (
        id BIGSERIAL PRIMARY KEY,
        text TEXT NOT NULL,
        user_id BIGINT NOT NULL,
        username TEXT,
        created_at TEXT NOT NULL,
        published_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_parts (
        id BIGSERIAL PRIMARY KEY,
        part1_hash TEXT NOT NULL,
        text TEXT NOT NULL,
        source_name TEXT NOT NULL,
        external_id TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        part1_msg_id BIGINT NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS submitted_jokes (
        id BIGSERIAL PRIMARY KEY,
        text TEXT NOT NULL,
        author_id BIGINT NOT NULL,
        author_username TEXT,
        author_name TEXT,
        submitted_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        moderator_message_id BIGINT,
        published_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tips (
        id BIGSERIAL PRIMARY KEY,
        submission_id BIGINT NOT NULL,
        author_id BIGINT NOT NULL,
        amount INTEGER NOT NULL,
        payer_id BIGINT,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shorts_candidates (
        id BIGSERIAL PRIMARY KEY,
        text TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'battle',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS locked_content (
        id BIGSERIAL PRIMARY KEY,
        joke_hash TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS authors (
        id BIGSERIAL PRIMARY KEY,
        telegram_id BIGINT UNIQUE NOT NULL,
        username TEXT,
        name TEXT NOT NULL,
        bio TEXT DEFAULT '',
        registered_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pending_quiz (
        id BIGSERIAL PRIMARY KEY,
        truncated_text TEXT NOT NULL,
        full_text TEXT NOT NULL,
        answer TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
]


class Database:
    def __init__(self, path_or_url: str) -> None:
        self.path_or_url = path_or_url
        self.is_postgres = path_or_url.startswith("postgres://") or path_or_url.startswith("postgresql://")
        if self.is_postgres and psycopg2 is None:
            raise RuntimeError("psycopg2-binary is required for PostgreSQL")
        if not self.is_postgres:
            self.path = Path(path_or_url)
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def connect(self) -> Iterator[object]:
        if self.is_postgres:
            connection = psycopg2.connect(self.path_or_url)
            connection.autocommit = False
            cursor_factory = psycopg2.extras.RealDictCursor
            try:
                yield connection
                connection.commit()
            finally:
                connection.close()
            return
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _exec(self, connection, sql: str, params: tuple = ()):
        if self.is_postgres:
            sql = sql.replace("?", "%s")
        return connection.execute(sql, params) if not self.is_postgres else connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor).execute(sql, params)

    def _fetchall(self, connection, sql: str, params: tuple = ()): 
        if self.is_postgres:
            cur = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql.replace("?", "%s"), params)
            return cur.fetchall()
        return connection.execute(sql, params).fetchall()

    def _fetchone(self, connection, sql: str, params: tuple = ()): 
        if self.is_postgres:
            cur = connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute(sql.replace("?", "%s"), params)
            return cur.fetchone()
        return connection.execute(sql, params).fetchone()

    def _initialize(self) -> None:
        with self.connect() as connection:
            if not self.is_postgres:
                connection.execute("PRAGMA journal_mode=WAL")
            for stmt in (POSTGRES_SCHEMA if self.is_postgres else SQLITE_SCHEMA):
                if self.is_postgres:
                    cur = connection.cursor()
                    cur.execute(stmt)
                    cur.close()
                else:
                    connection.execute(stmt)
            self._migrate(connection)

    def _migrate(self, connection) -> None:
        if self.is_postgres:
            cols = {row[0] for row in self._fetchall(connection, "SELECT column_name FROM information_schema.columns WHERE table_name = 'jokes'")}
            if "source_views" not in cols:
                cur = connection.cursor(); cur.execute("ALTER TABLE jokes ADD COLUMN source_views INTEGER NOT NULL DEFAULT 0"); cur.close()
            pending_cols = {row[0] for row in self._fetchall(connection, "SELECT column_name FROM information_schema.columns WHERE table_name = 'pending_parts'")}
            if "part1_msg_id" not in pending_cols:
                cur = connection.cursor(); cur.execute("ALTER TABLE pending_parts ADD COLUMN part1_msg_id BIGINT NOT NULL DEFAULT 0"); cur.close()
            return
        cols = [row[1] for row in connection.execute("PRAGMA table_info(jokes)").fetchall()]
        if "source_views" not in cols:
            connection.execute("ALTER TABLE jokes ADD COLUMN source_views INTEGER NOT NULL DEFAULT 0")
        pending_cols = [row[1] for row in connection.execute("PRAGMA table_info(pending_parts)").fetchall()]
        if "part1_msg_id" not in pending_cols:
            connection.execute("ALTER TABLE pending_parts ADD COLUMN part1_msg_id INTEGER NOT NULL DEFAULT 0")

    def _row_get(self, row, key: str):
        return row[key] if row is not None else None

    def _dict(self, row):
        return dict(row) if row else None

    def insert_joke(self, joke: Joke) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor()
                cur.execute(
                    "INSERT INTO jokes (text, source_name, source_url, external_id, content_hash, source_views, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (content_hash) DO NOTHING RETURNING id",
                    (joke.text, joke.source_name, joke.source_url, joke.external_id, joke.content_hash, joke.source_views, now),
                )
                row = cur.fetchone(); cur.close()
                return row is not None
            cur = c.execute(
                "INSERT OR IGNORE INTO jokes (text, source_name, source_url, external_id, content_hash, source_views, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (joke.text, joke.source_name, joke.source_url, joke.external_id, joke.content_hash, joke.source_views, now),
            )
            return cur.rowcount > 0

    def _get_published_dedup_keys(self) -> set[str]:
        with self.connect() as c:
            rows = self._fetchall(c, "SELECT text FROM jokes WHERE published_at IS NOT NULL")
        return {dedup_key(self._row_get(row, "text")) for row in rows}

    def _row_to_joke(self, row) -> Joke:
        return Joke(
            text=self._row_get(row, "text"),
            source_name=self._row_get(row, "source_name"),
            source_url=self._row_get(row, "source_url"),
            external_id=self._row_get(row, "external_id"),
            content_hash=self._row_get(row, "content_hash"),
            source_views=int(self._row_get(row, "source_views") or 0),
            created_at=datetime.fromisoformat(self._row_get(row, "created_at")) if self._row_get(row, "created_at") else None,
            published_at=datetime.fromisoformat(self._row_get(row, "published_at")) if self._row_get(row, "published_at") else None,
        )

    def get_next_unpublished(self) -> Joke | None:
        published_keys = self._get_published_dedup_keys()
        with self.connect() as c:
            rows = self._fetchall(c, "SELECT text, source_name, source_url, external_id, content_hash, source_views, created_at, published_at FROM jokes WHERE published_at IS NULL ORDER BY RANDOM()")
        for row in rows:
            if dedup_key(self._row_get(row, "text")) not in published_keys:
                return self._row_to_joke(row)
        return None

    def get_next_popular_unpublished(self) -> Joke | None:
        published_keys = self._get_published_dedup_keys()
        with self.connect() as c:
            rows = self._fetchall(c, "SELECT text, source_name, source_url, external_id, content_hash, source_views, created_at, published_at FROM jokes WHERE published_at IS NULL AND source_views > 0 ORDER BY source_views DESC, RANDOM()")
        for row in rows:
            if dedup_key(self._row_get(row, "text")) not in published_keys:
                return self._row_to_joke(row)
        return None

    def get_next_unpublished_matching(self, keywords: list[str], max_batch: int = 200) -> Joke | None:
        published_keys = self._get_published_dedup_keys()
        with self.connect() as c:
            rows = self._fetchall(c, "SELECT text, source_name, source_url, external_id, content_hash, source_views, created_at, published_at FROM jokes WHERE published_at IS NULL ORDER BY source_views DESC, RANDOM() LIMIT ?", (max_batch,))
        for row in rows:
            text = self._row_get(row, "text")
            if dedup_key(text) in published_keys:
                continue
            if not keywords or any(kw.lower() in text.lower() for kw in keywords):
                return self._row_to_joke(row)
        return None

    def mark_published(self, content_hash: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("UPDATE jokes SET published_at = %s WHERE content_hash = %s", (now, content_hash)); cur.close()
            else:
                c.execute("UPDATE jokes SET published_at = ? WHERE content_hash = ?", (now, content_hash))

    def dedup_unpublished(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        removed = 0
        with self.connect() as c:
            rows = self._fetchall(c, "SELECT content_hash, text, published_at FROM jokes ORDER BY created_at")
            seen: set[str] = set()
            for row in rows:
                key = dedup_key(self._row_get(row, "text"))
                if key in seen and self._row_get(row, "published_at") is None:
                    removed += 1
                    if self.is_postgres:
                        cur = c.cursor(); cur.execute("UPDATE jokes SET published_at = %s WHERE content_hash = %s", (now, self._row_get(row, "content_hash"))); cur.close()
                    else:
                        c.execute("UPDATE jokes SET published_at = ? WHERE content_hash = ?", (now, self._row_get(row, "content_hash")))
                else:
                    seen.add(key)
        return removed

    def _count(self, sql: str, params: tuple = ()) -> int:
        with self.connect() as c:
            row = self._fetchone(c, sql, params)
        return int(self._row_get(row, "count") or 0)

    def count_unpublished(self) -> int:
        return self._count("SELECT COUNT(*) AS count FROM jokes WHERE published_at IS NULL")

    def count_published(self) -> int:
        return self._count("SELECT COUNT(*) AS count FROM jokes WHERE published_at IS NOT NULL")

    def count_published_today(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d") + "%"
        return self._count("SELECT COUNT(*) AS count FROM jokes WHERE published_at LIKE ?", (today,))

    def mark_special_post(self, post_type: str) -> None:
        key = f"special_{post_type}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        if self.is_postgres:
            with self.connect() as c:
                cur = c.cursor(); cur.execute("INSERT INTO channel_meta (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, "1")); cur.close()
            return
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO channel_meta (key, value) VALUES (?, ?)", (key, "1"))

    def has_special_post_today(self, post_type: str) -> bool:
        key = f"special_{post_type}_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        with self.connect() as c:
            return self._fetchone(c, "SELECT value FROM channel_meta WHERE key = ?", (key,)) is not None

    def get_recent_published(self, limit: int = 3, days: int = 7) -> list[Joke]:
        with self.connect() as c:
            rows = self._fetchall(c, "SELECT text, source_name, source_url, external_id, content_hash, source_views, created_at, published_at FROM jokes WHERE published_at IS NOT NULL ORDER BY source_views DESC LIMIT ?", (limit * 3,))
        seen = set(); result = []
        for row in rows:
            text = self._row_get(row, "text")
            if text not in seen:
                seen.add(text)
                result.append(self._row_to_joke(row))
            if len(result) >= limit:
                break
        return result

    def save_pending_part(self, part1_hash: str, text: str, source_name: str, external_id: str, content_hash: str, part1_msg_id: int = 0) -> None:
        now = datetime.now(timezone.utc).isoformat()
        if self.is_postgres:
            with self.connect() as c:
                cur = c.cursor(); cur.execute("INSERT INTO pending_parts (part1_hash, text, source_name, external_id, content_hash, part1_msg_id, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", (part1_hash, text, source_name, external_id, content_hash, part1_msg_id, now)); cur.close(); return
        with self.connect() as c:
            c.execute("INSERT OR IGNORE INTO pending_parts (part1_hash, text, source_name, external_id, content_hash, part1_msg_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (part1_hash, text, source_name, external_id, content_hash, part1_msg_id, now))

    def get_pending_part(self):
        with self.connect() as c:
            row = self._fetchone(c, "SELECT text, source_name, external_id, content_hash, part1_msg_id FROM pending_parts ORDER BY created_at LIMIT 1")
        if row is None:
            return None
        return (Joke(text=self._row_get(row, "text"), source_name=self._row_get(row, "source_name"), source_url="", external_id=self._row_get(row, "external_id") + "_part2", content_hash=self._row_get(row, "content_hash")), int(self._row_get(row, "part1_msg_id") or 0))

    def delete_pending_part(self, content_hash: str) -> None:
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("DELETE FROM pending_parts WHERE content_hash = %s", (content_hash,)); cur.close()
            else:
                c.execute("DELETE FROM pending_parts WHERE content_hash = ?", (content_hash,))

    def save_locked_content(self, joke_hash: str, content: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("INSERT INTO locked_content (joke_hash, content, created_at) VALUES (%s,%s,%s) RETURNING id", (joke_hash, content, now)); row = cur.fetchone(); cur.close(); return int(row[0])
            cur = c.execute("INSERT INTO locked_content (joke_hash, content, created_at) VALUES (?, ?, ?)", (joke_hash, content, now))
            return int(cur.lastrowid)

    def get_locked_content(self, content_id: int) -> str | None:
        with self.connect() as c:
            row = self._fetchone(c, "SELECT content FROM locked_content WHERE id = ?", (content_id,))
        return self._row_get(row, "content") if row else None

    def save_submitted_joke(self, text: str, author_id: int, author_username: str | None, author_name: str | None) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("INSERT INTO submitted_jokes (text, author_id, author_username, author_name, submitted_at, status) VALUES (%s,%s,%s,%s,%s,'pending') RETURNING id", (text, author_id, author_username, author_name, now)); row = cur.fetchone(); cur.close(); return int(row[0])
            cur = c.execute("INSERT INTO submitted_jokes (text, author_id, author_username, author_name, submitted_at, status) VALUES (?, ?, ?, ?, ?, 'pending')", (text, author_id, author_username, author_name, now))
            return int(cur.lastrowid)

    def get_pending_submissions(self) -> list[dict]:
        with self.connect() as c:
            rows = self._fetchall(c, "SELECT id, text, author_id, author_username, author_name, submitted_at FROM submitted_jokes WHERE status = 'pending' ORDER BY submitted_at")
        return [dict(r) for r in rows]

    def set_moderator_message(self, joke_id: int, message_id: int) -> None:
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("UPDATE submitted_jokes SET moderator_message_id = %s WHERE id = %s", (message_id, joke_id)); cur.close()
            else:
                c.execute("UPDATE submitted_jokes SET moderator_message_id = ? WHERE id = ?", (message_id, joke_id))

    def approve_submission(self, joke_id: int) -> bool:
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("UPDATE submitted_jokes SET status = 'approved' WHERE id = %s AND status = 'pending'", (joke_id,)); rc = cur.rowcount; cur.close(); return rc > 0
            cur = c.execute("UPDATE submitted_jokes SET status = 'approved' WHERE id = ? AND status = 'pending'", (joke_id,)); return cur.rowcount > 0

    def reject_submission(self, joke_id: int) -> bool:
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("UPDATE submitted_jokes SET status = 'rejected' WHERE id = %s AND status = 'pending'", (joke_id,)); rc = cur.rowcount; cur.close(); return rc > 0
            cur = c.execute("UPDATE submitted_jokes SET status = 'rejected' WHERE id = ? AND status = 'pending'", (joke_id,)); return cur.rowcount > 0

    def get_next_approved_submission(self) -> dict | None:
        with self.connect() as c:
            row = self._fetchone(c, "SELECT id, text, author_id, author_username, author_name FROM submitted_jokes WHERE status = 'approved' AND published_at IS NULL ORDER BY submitted_at LIMIT 1")
        return dict(row) if row else None

    def mark_submission_published(self, joke_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("UPDATE submitted_jokes SET published_at = %s WHERE id = %s", (now, joke_id)); cur.close()
            else:
                c.execute("UPDATE submitted_jokes SET published_at = ? WHERE id = ?", (now, joke_id))

    def save_reaction(self, text: str, user_id: int, username: str | None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("INSERT INTO reactions (text, user_id, username, created_at) VALUES (%s,%s,%s,%s)", (text, user_id, username, now)); cur.close()
            else:
                c.execute("INSERT INTO reactions (text, user_id, username, created_at) VALUES (?, ?, ?, ?)", (text, user_id, username, now))

    def get_random_unpublished_reaction(self) -> dict | None:
        with self.connect() as c:
            row = self._fetchone(c, "SELECT id, text, username FROM reactions WHERE published_at IS NULL ORDER BY RANDOM() LIMIT 1")
        return dict(row) if row else None

    def mark_reaction_published(self, reaction_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("UPDATE reactions SET published_at = %s WHERE id = %s", (now, reaction_id)); cur.close()
            else:
                c.execute("UPDATE reactions SET published_at = ? WHERE id = ?", (now, reaction_id))

    def count_unpublished_reactions(self) -> int:
        return self._count("SELECT COUNT(*) AS count FROM reactions WHERE published_at IS NULL")

    def get_submission_author(self, joke_id: int) -> dict | None:
        with self.connect() as c:
            row = self._fetchone(c, "SELECT author_id, author_username, author_name FROM submitted_jokes WHERE id = ?", (joke_id,))
        return dict(row) if row else None

    def get_meta(self, key: str, default: str = "") -> str:
        with self.connect() as c:
            row = self._fetchone(c, "SELECT value FROM channel_meta WHERE key = ?", (key,))
        return self._row_get(row, "value") if row else default

    def set_meta(self, key: str, value: str) -> None:
        if self.is_postgres:
            with self.connect() as c:
                cur = c.cursor(); cur.execute("INSERT INTO channel_meta (key, value) VALUES (%s,%s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, value)); cur.close(); return
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO channel_meta (key, value) VALUES (?, ?)", (key, value))

    def count_approved_submissions(self) -> int:
        return self._count("SELECT COUNT(*) AS count FROM submitted_jokes WHERE status = 'approved' AND published_at IS NULL")

    def save_quiz(self, truncated_text: str, full_text: str, answer: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("INSERT INTO pending_quiz (truncated_text, full_text, answer, created_at) VALUES (%s,%s,%s,%s)", (truncated_text, full_text, answer, now)); cur.close()
            else:
                c.execute("INSERT INTO pending_quiz (truncated_text, full_text, answer, created_at) VALUES (?, ?, ?, ?)", (truncated_text, full_text, answer, now))

    def get_pending_quiz(self) -> dict | None:
        with self.connect() as c:
            row = self._fetchone(c, "SELECT id, full_text, answer FROM pending_quiz ORDER BY created_at LIMIT 1")
        return dict(row) if row else None

    def delete_pending_quiz(self, quiz_id: int) -> None:
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("DELETE FROM pending_quiz WHERE id = %s", (quiz_id,)); cur.close()
            else:
                c.execute("DELETE FROM pending_quiz WHERE id = ?", (quiz_id,))

    def count_pending_quiz(self) -> int:
        return self._count("SELECT COUNT(*) AS count FROM pending_quiz")

    def register_author(self, telegram_id: int, username: str | None, name: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        if self.is_postgres:
            with self.connect() as c:
                cur = c.cursor(); cur.execute("INSERT INTO authors (telegram_id, username, name, registered_at) VALUES (%s,%s,%s,%s) ON CONFLICT (telegram_id) DO NOTHING RETURNING id", (telegram_id, username, name, now)); row = cur.fetchone(); cur.close(); return row is not None
        with self.connect() as c:
            cur = c.execute("INSERT OR IGNORE INTO authors (telegram_id, username, name, registered_at) VALUES (?, ?, ?, ?)", (telegram_id, username, name, now))
            return cur.rowcount > 0

    def get_author_by_telegram_id(self, telegram_id: int) -> dict | None:
        with self.connect() as c:
            row = self._fetchone(c, "SELECT id, telegram_id, username, name, bio, registered_at FROM authors WHERE telegram_id = ?", (telegram_id,))
        return dict(row) if row else None

    def get_author_by_username(self, username: str) -> dict | None:
        with self.connect() as c:
            row = self._fetchone(c, "SELECT id, telegram_id, username, name, bio, registered_at FROM authors WHERE username = ?", (username.lstrip("@"),))
        return dict(row) if row else None

    def update_author_name(self, telegram_id: int, name: str) -> None:
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("UPDATE authors SET name = %s WHERE telegram_id = %s", (name, telegram_id)); cur.close()
            else:
                c.execute("UPDATE authors SET name = ? WHERE telegram_id = ?", (name, telegram_id))

    def get_top_authors(self, limit: int = 5, days: int = 7) -> list[dict]:
        with self.connect() as c:
            rows = self._fetchall(c, "SELECT a.id, a.username, a.name, a.telegram_id, COUNT(sj.id) AS jokes_count FROM authors a LEFT JOIN submitted_jokes sj ON sj.author_id = a.telegram_id AND sj.status = 'approved' AND sj.published_at IS NOT NULL GROUP BY a.id ORDER BY jokes_count DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def save_tip(self, submission_id: int, author_id: int, amount: int, payer_id: int | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("INSERT INTO tips (submission_id, author_id, amount, payer_id, created_at) VALUES (%s,%s,%s,%s,%s)", (submission_id, author_id, amount, payer_id, now)); cur.close()
            else:
                c.execute("INSERT INTO tips (submission_id, author_id, amount, payer_id, created_at) VALUES (?, ?, ?, ?, ?)", (submission_id, author_id, amount, payer_id, now))

    def get_author_total_tips(self, author_id: int) -> int:
        with self.connect() as c:
            row = self._fetchone(c, "SELECT COALESCE(SUM(amount), 0) AS total FROM tips WHERE author_id = ?", (author_id,))
        return int(self._row_get(row, "total") or 0)

    def get_author_published_count(self, telegram_id: int) -> int:
        return self._count("SELECT COUNT(*) AS count FROM submitted_jokes WHERE author_id = ? AND status = 'approved' AND published_at IS NOT NULL", (telegram_id,))

    def add_shorts_candidate(self, text: str, source: str = "battle") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("INSERT INTO shorts_candidates (text, source, created_at) VALUES (%s,%s,%s)", (text, source, now)); cur.close()
            else:
                c.execute("INSERT INTO shorts_candidates (text, source, created_at) VALUES (?, ?, ?)", (text, source, now))

    def count_shorts_candidates(self) -> int:
        return self._count("SELECT COUNT(*) AS count FROM shorts_candidates")

    def get_shorts_candidates(self, limit: int = 3) -> list[dict]:
        with self.connect() as c:
            rows = self._fetchall(c, "SELECT id, text, source, created_at FROM shorts_candidates ORDER BY RANDOM() LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def delete_shorts_candidate(self, candidate_id: int) -> None:
        with self.connect() as c:
            if self.is_postgres:
                cur = c.cursor(); cur.execute("DELETE FROM shorts_candidates WHERE id = %s", (candidate_id,)); cur.close()
            else:
                c.execute("DELETE FROM shorts_candidates WHERE id = ?", (candidate_id,))

    def get_youtube_last_video_id(self) -> str:
        return self.get_meta("youtube_last_video_id", "")

    def set_youtube_last_video_id(self, video_id: str) -> None:
        self.set_meta("youtube_last_video_id", video_id)
