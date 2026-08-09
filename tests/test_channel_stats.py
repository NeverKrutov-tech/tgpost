import tempfile
import unittest
from pathlib import Path

from src.tg_autopost.database import Database
from src.tg_autopost.models import Joke


class TestChannelStats(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "test.db"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_upsert_and_read(self):
        self.db.upsert_channel_stats("x0xotyh", 2600)
        self.assertEqual(self.db.get_channel_subscribers("x0xotyh"), 2600)

    def test_upsert_overwrites(self):
        self.db.upsert_channel_stats("x0xotyh", 100)
        self.db.upsert_channel_stats("x0xotyh", 2600)
        self.assertEqual(self.db.get_channel_subscribers("x0xotyh"), 2600)

    def test_missing_channel_returns_zero(self):
        self.assertEqual(self.db.get_channel_subscribers("nope"), 0)

    def test_joke_has_channel_fields(self):
        joke = Joke(
            text="t", source_name="tg/x0xotyh", source_url="u",
            external_id="e", content_hash="h", source_views=0,
        )
        self.assertEqual(joke.channel_subscribers, 0)
        self.assertEqual(joke.channel_name, "")


if __name__ == "__main__":
    unittest.main()
