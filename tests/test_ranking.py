import tempfile
import unittest
from pathlib import Path

from src.tg_autopost.database import Database
from src.tg_autopost.models import Joke
from src.tg_autopost.performance import PerformanceStore


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
        # Канал A: 1000 подписчиков, пост с 500 views (охват 50%)
        # Канал B: 100000 подписчиков, пост с 20000 views (охват 20%)
        self.db.upsert_channel_stats("small", 1000)
        self.db.upsert_channel_stats("big", 100000)
        # Оба текста равнокачественные (проходной)
        self.db.insert_joke(_joke("Мужчина заходит в бар, садится и говорит бармену:\n- Дай пива!\n- Пожалуйста.", "small", 500))
        self.db.insert_joke(_joke("Мужчина заходит в бар, садится и говорит бармену:\n- Дай водки!\n- Пожалуйста.", "big", 20000))

    def tearDown(self):
        self.tmp.cleanup()

    def test_higher_coverage_wins(self):
        joke = self.db.get_next_unpublished()
        self.assertIsNotNone(joke)
        self.assertEqual(joke.channel_name, "small")


class TestChannelEffectiveness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "perf.json"
        self.store = PerformanceStore(str(self.path))

    def tearDown(self):
        self.tmp.cleanup()

    def test_insufficient_data_defaults_to_one(self):
        eff = self.store.channel_effectiveness({})
        self.assertEqual(eff, {})

    def test_computes_ratio(self):
        data = {
            "1": {"views": 1000, "forwards": 2, "reactions": 0, "channel": "x"},
            "2": {"views": 1000, "forwards": 0, "reactions": 0, "channel": "y"},
            "3": {"views": 500, "forwards": 1, "reactions": 0, "channel": "x"},
            "4": {"views": 500, "forwards": 0, "reactions": 0, "channel": "y"},
        }
        eff = self.store.channel_effectiveness(data, min_posts=2)
        self.assertIn("x", eff)
        self.assertLess(eff["y"], eff["x"])


if __name__ == "__main__":
    unittest.main()
