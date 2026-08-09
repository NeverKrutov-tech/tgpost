import tempfile
import unittest
from pathlib import Path

from src.tg_autopost.database import Database
from src.tg_autopost.models import Joke


def _joke(text, source, views):
    return Joke(
        text=text, source_name=f"tg/{source}", source_url=f"https://t.me/s/{source}",
        external_id=f"e-{hash(text)}", content_hash=f"h-{abs(hash(text))}",
        source_views=views, channel_name=source,
    )


class TestRanking(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "test.db"))
        self.db.upsert_channel_stats("small", 1000)
        self.db.upsert_channel_stats("big", 100000)
        self.db.insert_joke(_joke("Мужчина заходит в бар, садится и говорит бармену:\n- Дай пива!\n- Пожалуйста.", "small", 500))
        self.db.insert_joke(_joke("Мужчина заходит в бар, садится и говорит бармену:\n- Дай водки!\n- Пожалуйста.", "big", 20000))

    def tearDown(self):
        self.tmp.cleanup()

    def test_higher_coverage_wins(self):
        joke = self.db.get_next_unpublished()
        self.assertIsNotNone(joke)
        self.assertEqual(joke.channel_name, "small")


if __name__ == "__main__":
    unittest.main()
