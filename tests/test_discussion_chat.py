import os
import unittest

from src.tg_autopost.config import load_settings
from src.tg_autopost.publisher import _build_text


class TestDiscussionChatLink(unittest.TestCase):
    def setUp(self):
        os.environ["BOT_TOKEN"] = "test:token"
        os.environ["CHANNEL_ID"] = "-100123"
        os.environ["CHANNEL_LINK"] = "https://t.me/main"
        os.environ["DISCUSSION_CHAT_LINK"] = "https://t.me/chat"

    def tearDown(self):
        for k in ("BOT_TOKEN", "CHANNEL_ID", "CHANNEL_LINK", "DISCUSSION_CHAT_LINK"):
            os.environ.pop(k, None)

    def test_settings_has_discussion_chat_link(self):
        s = load_settings()
        self.assertEqual(s.discussion_chat_link, "https://t.me/chat")

    def test_settings_discussion_chat_link_empty_when_unset(self):
        os.environ.pop("DISCUSSION_CHAT_LINK", None)
        s = load_settings()
        self.assertEqual(s.discussion_chat_link, "")

    def test_settings_discussion_chat_link_invalid_prefix_warns_and_clears(self):
        os.environ["DISCUSSION_CHAT_LINK"] = "javascript:alert(1)"
        s = load_settings()
        self.assertEqual(s.discussion_chat_link, "")

    def test_settings_accepts_tme_short_link(self):
        os.environ["DISCUSSION_CHAT_LINK"] = "t.me/chat"
        s = load_settings()
        self.assertEqual(s.discussion_chat_link, "t.me/chat")

    def test_build_text_appends_discussion_line(self):
        text = _build_text(
            "\u0410\u043D\u0435\u043A\u0434\u043E\u0442 \u0442\u0435\u043A\u0441\u0442.",
            {"emoji": "\U0001F60A", "preamble": ""},
            1,
            preamble_override="",
            is_part2=False,
            channel_link="",
            discussion_chat_link="https://t.me/chat",
        )
        self.assertIn("\U0001F4AC \u041E\u0431\u0441\u0443\u0434\u0438\u0442\u044C \u0432 \u0447\u0430\u0442\u0435 \u2192 https://t.me/chat", text)

    def test_build_text_omits_discussion_when_empty(self):
        text = _build_text(
            "\u0410\u043D\u0435\u043A\u0434\u043E\u0442.",
            {"emoji": "\U0001F60A", "preamble": ""},
            1,
            preamble_override="",
            is_part2=False,
            channel_link="",
            discussion_chat_link="",
        )
        self.assertNotIn("\u041E\u0431\u0441\u0443\u0434\u0438\u0442\u044C", text)

    def test_build_keyboard_adds_button_when_link_set(self):
        from src.tg_autopost.publisher import TelegramPublisher
        from types import SimpleNamespace
        publisher = TelegramPublisher.__new__(TelegramPublisher)
        publisher.settings = SimpleNamespace(
            channel_link="https://t.me/main",
            discussion_chat_link="https://t.me/chat",
        )
        kb = publisher._build_keyboard(message_id=42)
        flat = [b for row in kb["inline_keyboard"] for b in row]
        texts = [b["text"] for b in flat]
        self.assertIn("\U0001F4AC \u041E\u0431\u0441\u0443\u0434\u0438\u0442\u044C", texts)
        self.assertEqual([b for b in flat if b["text"] == "\U0001F4AC \u041E\u0431\u0441\u0443\u0434\u0438\u0442\u044C"][0]["url"],
                         "https://t.me/chat")

    def test_build_keyboard_no_button_when_link_empty(self):
        from src.tg_autopost.publisher import TelegramPublisher
        from types import SimpleNamespace
        publisher = TelegramPublisher.__new__(TelegramPublisher)
        publisher.settings = SimpleNamespace(
            channel_link="https://t.me/main",
            discussion_chat_link="",
        )
        kb = publisher._build_keyboard(message_id=42)
        flat = [b for row in kb["inline_keyboard"] for b in row]
        texts = [b["text"] for b in flat]
        self.assertNotIn("\U0001F4AC \u041E\u0431\u0441\u0443\u0434\u0438\u0442\u044C", texts)


if __name__ == "__main__":
    unittest.main()
