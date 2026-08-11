"""Регрессионные тесты для багов, найденных при полном аудите 2026-08-11.

Каждый тест ловит конкретный сбой:
- _send_teaser передавал dict в get_hashtags -> AttributeError, пост терялся;
- _try_make_quiz наращивал счётчик только при срабатывании -> квиз выходил один раз;
- _friday_prompt_posted_today игнорировал маркер-файл и крутил getUpdates без offset.
"""
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from src.tg_autopost import publisher as publisher_mod
from src.tg_autopost.publisher import TelegramPublisher

LONG_JOKE = (
    "- Доктор, у меня каждое утро болит голова, а вечером "
    "я забываю, что хотел сделать.\n"
    "- Это вы ко мне пришли или я к вам?\n"
    "- А кто вы?\n"
    "Этот анекдот достаточно длинный, чтобы попасть под teaser-ветку, "
    "и он содержит больше двухсот символов текста для проверки."
)


def _make_publisher(requests_mock):
    settings = SimpleNamespace(
        bot_token="test:token",
        channel_id="-1001",
        channel_link="https://t.me/main",
        discussion_chat_link="",
        http_timeout=10,
        vk_token="",
        vk_owner_id=0,
        youtube_refresh_token="",
        youtube_api_key="",
        youtube_channel_id="",
        youtube_client_id="",
        youtube_client_secret="",
        kie_api_key="",
        cf_account_id="",
        cf_api_token="",
    )
    db = mock.Mock()
    db.connect = mock.MagicMock()
    p = TelegramPublisher.__new__(TelegramPublisher)
    p.settings = settings
    p.db = db
    return p


class TeaserDoesNotCrashTest(unittest.TestCase):
    def test_send_teaser_publishes_long_joke(self):
        with mock.patch.object(publisher_mod.requests, "post") as rpost:
            rpost.return_value = SimpleNamespace(
                ok=True, json=lambda: {"ok": True, "result": {"message_id": 77}}
            )
            p = _make_publisher(rpost)
            p.db.save_locked_content.return_value = 5
            p.db.count_published.return_value = 10

            joke = SimpleNamespace(
                text=LONG_JOKE,
                content_hash="abc",
                external_id="e1",
            )
            result = p._send_teaser(joke, {"emoji": "\U0001F602", "keywords": []})
            self.assertTrue(result)
            p.db.mark_published.assert_called_with("abc", 77)


class QuizCounterEveryEighthPostTest(unittest.TestCase):
    def _publisher(self):
        db = mock.Mock()
        state = {"quiz_counter": "0"}

        def _get_meta(key, default="0"):
            return state.get(key, default)

        def _set_meta(key, value):
            state[key] = value

        db.get_meta.side_effect = _get_meta
        db.set_meta.side_effect = _set_meta
        p = TelegramPublisher.__new__(TelegramPublisher)
        p.settings = SimpleNamespace(
            bot_token="t", channel_id="-1", channel_link="", discussion_chat_link="",
            http_timeout=10,
        )
        p._bot_username = "bot"
        db.connect = mock.MagicMock()
        p.db = db
        return p, db, state

    def _joke(self, n):
        return SimpleNamespace(
            text=(
                f"- Строка номер {n} из очень длинного анекдота про программиста "
                f"и его начальника в субботу утром.\n"
                f"- Вторая строка номер {n} продолжает историю про офис и кофе.\n"
                f"- А это финальная строка номер {n}, которая заканчивает шутку."
            ),
            content_hash=f"h{n}",
            external_id=f"e{n}",
        )

    def test_quiz_fires_every_eighth_call_then_keeps_counting(self):
        p, db, state = self._publisher()
        with mock.patch.object(publisher_mod.requests, "post") as rpost:
            rpost.return_value = SimpleNamespace(
                ok=True, json=lambda: {"ok": True, "result": {"message_id": 1}}
            )
            fired = []
            for i in range(1, 17):
                res = p._try_make_quiz(self._joke(i), {"emoji": "\U0001F602"})
                fired.append(res is True)
            # 8-й и 16-й посты — квиз; остальные — нет.
            self.assertEqual(fired, [False] * 7 + [True] + [False] * 7 + [True])
            self.assertEqual(state["quiz_counter"], "16")

    def test_quiz_counter_advances_even_when_not_fired(self):
        p, db, state = self._publisher()
        with mock.patch.object(publisher_mod.requests, "post") as rpost:
            rpost.return_value = SimpleNamespace(
                ok=True, json=lambda: {"ok": True, "result": {"message_id": 1}}
            )
            for _ in range(3):
                p._try_make_quiz(self._joke(1), {"emoji": "\U0001F602"})
            # Счётчик должен дойти до 3, а не застрять на 1.
            self.assertEqual(state["quiz_counter"], "3")


class FridayMarkerCheckTest(unittest.TestCase):
    def setUp(self):
        self.marker = Path("data/friday_marker.txt")
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self._had = self.marker.exists()
        self._old = self.marker.read_text(encoding="utf-8") if self._had else None

    def tearDown(self):
        if self._had:
            self.marker.write_text(self._old, encoding="utf-8")
        elif self.marker.exists():
            self.marker.unlink()

    def test_friday_marker_read_before_any_telegram_scan(self):
        from datetime import datetime
        today = datetime.today().strftime("%Y-%m-%d")
        self.marker.write_text(today, encoding="utf-8")
        p = _make_publisher(None)
        with mock.patch.object(publisher_mod.requests, "post") as rpost:
            self.assertTrue(p._friday_prompt_posted_today())
            rpost.assert_not_called()  # не должны идти в Telegram

    def test_stale_marker_still_reads_but_returns_false_without_crash(self):
        self.marker.write_text("2000-01-01", encoding="utf-8")
        p = _make_publisher(None)
        with mock.patch.object(publisher_mod.requests, "post") as rpost:
            rpost.return_value = SimpleNamespace(
                ok=False, json=lambda: {"ok": False, "description": "x"}
            )
            self.assertFalse(p._friday_prompt_posted_today())


if __name__ == "__main__":
    unittest.main()
