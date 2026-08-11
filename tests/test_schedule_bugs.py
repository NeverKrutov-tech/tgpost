"""Регрессионные тесты: БД «лучшее за неделю» и расписание cron-слотов.

Ловят:
- get_recent_published игнорировал параметр days (ежедневный дайджест показывал
  топ за всё время);
- run_catchup и маппинг /cron/joke держали старое расписание 10/14/20, хотя
  реальное стало 08/13/21;
- /debug показывал несуществующие слоты.
"""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


class RecentPublishedRespectsDaysTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(str(Path(self.tmp.name) / "test.db"))
        self.db.upsert_channel_stats("test", 1000)

    def tearDown(self):
        self.tmp.cleanup()

    def _mark_published_at(self, content_hash: str, when: datetime) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE jokes SET published_at = ? WHERE content_hash = ?",
                (when.isoformat(), content_hash),
            )

    def test_old_published_jokes_are_excluded_from_weekly_window(self):
        now = datetime.now(timezone.utc)
        recent = _joke("Свежий анекдот про кота который вчера утром упал.", "a")
        old = _joke("Старый анекдот про программиста и его жену в прошлом.", "b")
        self.db.insert_joke(recent)
        self.db.insert_joke(old)
        self._mark_published_at(recent.content_hash, now)
        self._mark_published_at(old.content_hash, now - timedelta(days=30))

        result = self.db.get_recent_published(limit=5, days=7)
        texts = {j.text for j in result}
        self.assertIn(recent.text, texts)
        self.assertNotIn(old.text, texts)


class CatchupScheduleMatchesNewSlotsTest(unittest.TestCase):
    def test_catchup_schedule_uses_current_slots(self):
        from src.tg_autopost.app import CATCHUP_SCHEDULE
        slots = {action for action, hour, minute, _ in CATCHUP_SCHEDULE}
        self.assertIn("joke_08", slots)
        self.assertIn("joke_13", slots)
        self.assertIn("joke_21", slots)
        self.assertNotIn("newsjacker", slots)


class CronJokeSlotMappingTest(unittest.TestCase):
    def test_hour_maps_to_correct_lock_key(self):
        from src.tg_autopost.render_web import _joke_lock_key
        self.assertEqual(_joke_lock_key(8), "joke_08")
        self.assertEqual(_joke_lock_key(13), "joke_13")
        self.assertEqual(_joke_lock_key(21), "joke_21")


class DebugSlotsTest(unittest.TestCase):
    def test_debug_slot_names_match_current_schedule(self):
        from src.tg_autopost.render_web import DEBUG_JOKE_SLOTS, DEBUG_CRON_LOCKS
        self.assertIn("joke_08", DEBUG_JOKE_SLOTS)
        self.assertIn("joke_13", DEBUG_JOKE_SLOTS)
        self.assertIn("joke_21", DEBUG_JOKE_SLOTS)
        self.assertNotIn("joke_10", DEBUG_JOKE_SLOTS)
        self.assertNotIn("newsjacker", DEBUG_CRON_LOCKS)


if __name__ == "__main__":
    unittest.main()
