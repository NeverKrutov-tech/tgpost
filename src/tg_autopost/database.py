import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Tuple

from .models import Joke
from .utils import build_hash, dedup_key

PUBLISHED_KEYS_FILE = "data/published_keys.txt"


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
    part1_msg_id INTEGER NOT NULL DEFAULT 0,
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

TIPS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id INTEGER NOT NULL,
    author_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    payer_id INTEGER,
    created_at TEXT NOT NULL
);
"""

SHORTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS shorts_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'battle',
    created_at TEXT NOT NULL
);
"""

LOCKED_CONTENT_SQL = """
CREATE TABLE IF NOT EXISTS locked_content (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    joke_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

AUTHORS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    name TEXT NOT NULL,
    bio TEXT DEFAULT '',
    registered_at TEXT NOT NULL
);
"""

QUIZ_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pending_quiz (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    truncated_text TEXT NOT NULL,
    full_text TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

SUBSCRIBERS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS bot_subscribers (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    subscribed_at TEXT NOT NULL
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
            connection.execute(QUIZ_TABLE_SQL)
            connection.execute(AUTHORS_TABLE_SQL)
            connection.execute(TIPS_TABLE_SQL)
            connection.execute(SHORTS_TABLE_SQL)
            connection.execute(LOCKED_CONTENT_SQL)
            connection.execute(SUBSCRIBERS_TABLE_SQL)
            self._migrate(connection)

    def _migrate(self, connection: sqlite3.Connection) -> None:
        cols = [row[1] for row in connection.execute("PRAGMA table_info(jokes)").fetchall()]
        if "source_views" not in cols:
            connection.execute("ALTER TABLE jokes ADD COLUMN source_views INTEGER NOT NULL DEFAULT 0")
        if "telegram_msg_id" not in cols:
            connection.execute("ALTER TABLE jokes ADD COLUMN telegram_msg_id INTEGER")
        pending_cols = [row[1] for row in connection.execute("PRAGMA table_info(pending_parts)").fetchall()]
        if "part1_msg_id" not in pending_cols:
            connection.execute("ALTER TABLE pending_parts ADD COLUMN part1_msg_id INTEGER NOT NULL DEFAULT 0")

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

    def _load_published_keys_file(self) -> set[str]:
        path = Path(PUBLISHED_KEYS_FILE)
        if not path.exists():
            return set()
        try:
            keys = {
                line.strip()
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            }
            return keys
        except Exception:
            return set()

    def _append_published_key(self, key: str) -> None:
        if not key:
            return
        path = Path(PUBLISHED_KEYS_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(key + "\n")
        except Exception:
            pass

    def _get_published_dedup_keys(self) -> set[str]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT text FROM jokes WHERE published_at IS NOT NULL"
            ).fetchall()
        keys = {dedup_key(row["text"]) for row in rows}
        # Use file-based keys only when SQLite has no published history (cache reset)
        if not keys:
            keys |= self._load_published_keys_file()
        return keys

    def get_next_unpublished(self) -> Joke | None:
        published_keys = self._get_published_dedup_keys()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT text, source_name, source_url, external_id, content_hash, source_views, created_at, published_at
                FROM jokes
                WHERE published_at IS NULL
                ORDER BY RANDOM()
                """
            ).fetchall()

        for row in rows:
            if dedup_key(row["text"]) not in published_keys:
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
        return None

    def get_next_popular_unpublished(self) -> Joke | None:
        published_keys = self._get_published_dedup_keys()
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT text, source_name, source_url, external_id, content_hash, source_views, created_at, published_at
                FROM jokes
                WHERE published_at IS NULL AND source_views > 0
                ORDER BY source_views DESC, RANDOM()
                """
            ).fetchall()
        for row in rows:
            if dedup_key(row["text"]) not in published_keys:
                return Joke(
                    text=row["text"],
                    source_name=row["source_name"],
                    source_url=row["source_url"],
                    external_id=row["external_id"],
                    content_hash=row["content_hash"],
                    source_views=row["source_views"],
                )
        return None

    def get_next_unpublished_matching(self, keywords: list[str], max_batch: int = 200) -> Joke | None:
        published_keys = self._get_published_dedup_keys()
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
            if dedup_key(row["text"]) in published_keys:
                continue
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

    def get_unpublished_meme(self) -> Joke | None:
        published_keys = self._get_published_dedup_keys()
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT text, source_name, source_url, external_id, content_hash, source_views, created_at, published_at "
                "FROM jokes WHERE published_at IS NULL AND source_name = 'meme_api' ORDER BY RANDOM()"
            ).fetchall()
        for row in rows:
            if dedup_key(row["text"]) not in published_keys:
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
        return None

    def mark_published(self, content_hash: str, telegram_msg_id: int | None = None) -> None:
        published_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            row = connection.execute(
                "SELECT text FROM jokes WHERE content_hash = ?", (content_hash,)
            ).fetchone()
            if row is not None:
                self._append_published_key(dedup_key(row["text"]))
            if telegram_msg_id:
                connection.execute(
                    "UPDATE jokes SET published_at = ?, telegram_msg_id = ? WHERE content_hash = ?",
                    (published_at, telegram_msg_id, content_hash),
                )
            else:
                connection.execute(
                    "UPDATE jokes SET published_at = ? WHERE content_hash = ?",
                    (published_at, content_hash),
                )

    def dedup_unpublished(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        removed = 0
        with self.connect() as connection:
            all_rows = connection.execute(
                "SELECT content_hash, text, published_at FROM jokes ORDER BY created_at"
            ).fetchall()
            seen: set[str] = set()
            for row in all_rows:
                key = dedup_key(row["text"])
                if key in seen:
                    if row["published_at"] is None:
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

    def get_random_published_msg_id(self) -> int | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT telegram_msg_id FROM jokes WHERE telegram_msg_id IS NOT NULL ORDER BY RANDOM() LIMIT 1"
            ).fetchone()
            return int(row["telegram_msg_id"]) if row else None

    def mark_special_post(self, post_type: str) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO channel_meta (key, value) VALUES (?, ?)",
                (f"special_{post_type}_{today}", "1"),
            )

    def has_special_post_today(self, post_type: str) -> bool:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with self.connect() as connection:
            row = connection.execute(
                "SELECT value FROM channel_meta WHERE key = ?",
                (f"special_{post_type}_{today}",),
            ).fetchone()
            return row is not None

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

    def get_joke_by_id(self, joke_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, text, source_name, published_at, telegram_msg_id FROM jokes WHERE id = ?",
                (joke_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_published_by_keywords(self, keywords: list[str], limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, text, published_at FROM jokes WHERE published_at IS NOT NULL "
                "ORDER BY published_at DESC"
            ).fetchall()
        results = []
        for row in rows:
            if not keywords or any(kw.lower() in row["text"].lower() for kw in keywords):
                results.append({"id": row["id"], "text": row["text"], "published_at": row["published_at"]})
                if len(results) >= limit:
                    break
        return results

    def save_pending_part(self, part1_hash: str, text: str, source_name: str, external_id: str, content_hash: str, part1_msg_id: int = 0) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO pending_parts (part1_hash, text, source_name, external_id, content_hash, part1_msg_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (part1_hash, text, source_name, external_id, content_hash, part1_msg_id, now),
            )

    def get_pending_part(self) -> Tuple["Joke", int] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT text, source_name, external_id, content_hash, part1_msg_id FROM pending_parts ORDER BY created_at LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return (
            Joke(
                text=row["text"],
                source_name=row["source_name"],
                source_url="",
                external_id=row["external_id"] + "_part2",
                content_hash=row["content_hash"],
            ),
            row["part1_msg_id"],
        )

    def delete_pending_part(self, content_hash: str) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM pending_parts WHERE content_hash = ?", (content_hash,))

    def save_locked_content(self, joke_hash: str, content: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO locked_content (joke_hash, content, created_at) VALUES (?, ?, ?)",
                (joke_hash, content, now),
            )
            return int(cursor.lastrowid)

    def get_locked_content(self, content_id: int) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT content FROM locked_content WHERE id = ?", (content_id,)
            ).fetchone()
        return row["content"] if row else None

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
            row = connection.execute(
                "SELECT text FROM submitted_jokes WHERE id = ?", (joke_id,)
            ).fetchone()
            if row is not None:
                self._append_published_key(dedup_key(row["text"]))
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
            row = connection.execute(
                "SELECT text FROM reactions WHERE id = ?", (reaction_id,)
            ).fetchone()
            if row is not None:
                self._append_published_key(dedup_key(row["text"]))
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

    def save_quiz(self, truncated_text: str, full_text: str, answer: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO pending_quiz (truncated_text, full_text, answer, created_at) VALUES (?, ?, ?, ?)",
                (truncated_text, full_text, answer, now),
            )

    def get_pending_quiz(self) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, full_text, answer FROM pending_quiz ORDER BY created_at LIMIT 1"
            ).fetchone()
            return dict(row) if row else None

    def delete_pending_quiz(self, quiz_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM pending_quiz WHERE id = ?", (quiz_id,))

    def count_pending_quiz(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM pending_quiz").fetchone()
            return int(row["count"])

    def register_author(self, telegram_id: int, username: str | None, name: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO authors (telegram_id, username, name, registered_at) VALUES (?, ?, ?, ?)",
                (telegram_id, username, name, now),
            )
            return cursor.rowcount > 0

    def get_author_by_telegram_id(self, telegram_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, telegram_id, username, name, bio, registered_at FROM authors WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
            return dict(row) if row else None

    def get_author_by_username(self, username: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, telegram_id, username, name, bio, registered_at FROM authors WHERE username = ?",
                (username.lstrip("@"),),
            ).fetchone()
            return dict(row) if row else None

    def update_author_name(self, telegram_id: int, name: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE authors SET name = ? WHERE telegram_id = ?",
                (name, telegram_id),
            )

    def get_top_authors(self, limit: int = 5, days: int = 7) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT a.id, a.username, a.name, a.telegram_id,
                       COUNT(sj.id) AS jokes_count
                FROM authors a
                LEFT JOIN submitted_jokes sj ON sj.author_id = a.telegram_id
                    AND sj.status = 'approved' AND sj.published_at IS NOT NULL
                GROUP BY a.id
                ORDER BY jokes_count DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def save_tip(self, submission_id: int, author_id: int, amount: int, payer_id: int | None = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO tips (submission_id, author_id, amount, payer_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (submission_id, author_id, amount, payer_id, now),
            )

    def get_author_total_tips(self, author_id: int) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(amount), 0) AS total FROM tips WHERE author_id = ?",
                (author_id,),
            ).fetchone()
            return int(row["total"])

    def get_author_published_count(self, telegram_id: int) -> int:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM submitted_jokes WHERE author_id = ? AND status = 'approved' AND published_at IS NOT NULL",
                (telegram_id,),
            ).fetchone()
            return int(row["count"])

    def subscribe_user(self, user_id: int, username: str | None = None) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO bot_subscribers (user_id, username, subscribed_at) VALUES (?, ?, ?)",
                (user_id, username, now),
            )
            return cursor.rowcount > 0

    def unsubscribe_user(self, user_id: int) -> bool:
        with self.connect() as connection:
            cursor = connection.execute(
                "DELETE FROM bot_subscribers WHERE user_id = ?", (user_id,)
            )
            return cursor.rowcount > 0

    def is_subscribed(self, user_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM bot_subscribers WHERE user_id = ?", (user_id,)
            ).fetchone()
            return row is not None

    def get_all_subscribers(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT user_id, username FROM bot_subscribers ORDER BY subscribed_at"
            ).fetchall()
            return [dict(r) for r in rows]

    def add_shorts_candidate(self, text: str, source: str = "battle") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO shorts_candidates (text, source, created_at) VALUES (?, ?, ?)",
                (text, source, now),
            )

    def count_shorts_candidates(self) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM shorts_candidates").fetchone()
            return int(row["count"])

    def get_shorts_candidates(self, limit: int = 3) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id, text, source, created_at FROM shorts_candidates ORDER BY RANDOM() LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_shorts_candidate(self, candidate_id: int) -> None:
        with self.connect() as connection:
            connection.execute("DELETE FROM shorts_candidates WHERE id = ?", (candidate_id,))

    def get_youtube_last_video_id(self) -> str:
        return self.get_meta("youtube_last_video_id", "")

    def set_youtube_last_video_id(self, video_id: str) -> None:
        self.set_meta("youtube_last_video_id", video_id)
