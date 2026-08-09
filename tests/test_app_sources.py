import os
import tempfile
import unittest
from pathlib import Path


class TestAppSources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_environ = dict(os.environ)
        os.environ["BOT_TOKEN"] = "test:token"
        os.environ["CHANNEL_ID"] = "-100123"
        os.environ["TELEGRAM_SOURCES"] = "x0xotyh,anekdot_x"
        os.environ["DATABASE_PATH"] = str(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_environ)
        self.tmp.cleanup()

    def test_no_site_sources(self):
        from src.tg_autopost.app import build_services
        settings, db, ingestor, publisher = build_services()
        names = [s.name for s in ingestor.sources]
        self.assertTrue(all(n not in names for n in ("anekdot.ru", "anekdotov.net", "baneks.ru", "it_jokes", "reddit_jokes")))
        self.assertTrue(any(n.startswith("tg/") or n == "telegram" for n in names))


if __name__ == "__main__":
    unittest.main()
