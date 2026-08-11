import tempfile
import unittest
from pathlib import Path

from src.tg_autopost.database import Database
from src.tg_autopost.models import Joke
from src.tg_autopost.utils import build_hash


def _joke(text: str, ext: str) -> Joke:
    return Joke(
        text=text,
        source_name="tg/test",
        source_url="https://t.me/s/test",
        external_id=ext,
        content_hash=build_hash(text),
        source_views=10,
        channel_name="test",
    )


A = "Первый анекдот про кота который сломал вазу вчера утром."
B = "Второй анекдот про программиста и его жену в субботу."


class BattlePicksTwoDistinctJokesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "test.db"))
        self.db.upsert_channel_stats("test", 1000)

    def tearDown(self):
        self.tmp.cleanup()

    def test_exclude_returns_a_different_joke(self):
        self.db.insert_joke(_joke(A, "a"))
        self.db.insert_joke(_joke(B, "b"))
        first = self.db.get_next_unpublished()
        self.assertIsNotNone(first)

        second = self.db.get_next_unpublished(exclude_hashes={first.content_hash})
        self.assertIsNotNone(second, "must find a second, different joke")
        self.assertNotEqual(first.content_hash, second.content_hash)

    def test_exclude_returns_none_when_pool_exhausted(self):
        self.db.insert_joke(_joke(A, "a"))
        only = self.db.get_next_unpublished()
        self.assertIsNotNone(only)
        self.assertIsNone(
            self.db.get_next_unpublished(exclude_hashes={only.content_hash})
        )


if __name__ == "__main__":
    unittest.main()
