import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from src.tg_autopost.database import Database
from src.tg_autopost.models import Joke
from src.tg_autopost.sources.telegram_channel import _parse_subscribers


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


class TestSubscriberParsing(unittest.TestCase):
    def test_plain_number(self):
        soup = BeautifulSoup('<div class="tgme_channel_info_count">2 600 subscribers</div>', "html.parser")
        self.assertEqual(_parse_subscribers(soup), 2600)

    def test_thousands_suffix(self):
        soup = BeautifulSoup('<div class="tgme_channel_info_count">2.6K subscribers</div>', "html.parser")
        self.assertEqual(_parse_subscribers(soup), 2600)

    def test_russian_word(self):
        soup = BeautifulSoup('<div class="tgme_channel_info_count">1.2М подписчиков</div>', "html.parser")
        self.assertEqual(_parse_subscribers(soup), 1200000)

    def test_no_count(self):
        soup = BeautifulSoup('<div class="tgme_widget_message_wrap"></div>', "html.parser")
        self.assertEqual(_parse_subscribers(soup), 0)


if __name__ == "__main__":
    unittest.main()
