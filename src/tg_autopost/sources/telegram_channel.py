import logging
import re
import time
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from ..models import Joke
from ..utils import build_hash, normalize_text
from .base import JokeSource

logger = logging.getLogger(__name__)

TME_URL = "https://t.me/s/{channel}"

SKIP_PATTERNS = [
    re.compile(r"https?://", re.I),
    re.compile(r"@\w+"),
    re.compile(r"tg://"),
    re.compile(r"t\.me/"),
    re.compile(r"^\d+$"),
]

AD_PHRASES = [
    "\u0447\u0438\u0442\u0430\u0442\u044C \u043F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435",
    "\u0447\u0438\u0442\u0430\u0439\u0442\u0435 \u043F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435",
    "\u043F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435 \u0432",
    "\u043F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C",
    "\u043F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C \u043D\u0430",
    "\u0440\u0435\u043A\u043B\u0430\u043C\u0430",
    "\u0440\u0435\u043A\u043B\u0430\u043C\u043D\u044B\u0439 \u043F\u043E\u0441\u0442",
]

MIN_LENGTH = 30
MAX_LENGTH = 3000


class TelegramChannelSource(JokeSource):
    name = "telegram"

    def __init__(self, channels: list[str], timeout: int = 20) -> None:
        self.channels = [ch.lstrip("@") for ch in channels if ch.strip()]
        self.timeout = timeout

    def fetch(self, limit: int) -> Iterable[Joke]:
        for channel in self.channels:
            url = TME_URL.format(channel=channel)
            try:
                response = requests.get(
                    url,
                    timeout=self.timeout,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                )
                response.raise_for_status()
            except Exception:
                logger.warning("Failed to fetch t.me/s/%s", channel)
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            messages = soup.select("div.tgme_widget_message_wrap")
            if not messages:
                logger.info("No messages found on t.me/s/%s", channel)
                continue

            yielded = 0
            for msg_wrap in messages:
                msg = msg_wrap.select_one("div.tgme_widget_message")
                if msg is None:
                    continue

                if msg.select_one("div.tgme_widget_message_photo_wrap, div.tgme_widget_message_video_wrap"):
                    continue
                if msg.select_one("a.tgme_widget_message_link_preview"):
                    continue
                if msg.select_one("a.tgme_widget_message_inline_button_url"):
                    continue

                text_div = msg.select_one("div.tgme_widget_message_text")
                if text_div is None:
                    continue

                raw_text = text_div.get_text("\n", strip=True)
                if not raw_text or len(raw_text) < MIN_LENGTH or len(raw_text) > MAX_LENGTH:
                    continue
                if any(p.search(raw_text) for p in SKIP_PATTERNS):
                    continue
                raw_lower = raw_text.lower()
                if any(phrase in raw_lower for phrase in AD_PHRASES):
                    continue

                text = normalize_text(raw_text)
                if not text or len(text) < MIN_LENGTH:
                    continue

                views_el = msg.select_one("span.tgme_widget_message_views")
                views = 0
                if views_el:
                    views_text = views_el.get_text(strip=True)
                    views_text = views_text.replace("\u00A0", "").replace(",", "").replace(".", "")
                    if views_text:
                        try:
                            views = int(views_text)
                        except ValueError:
                            views = 0

                external_id = f"tg_{channel}_{abs(hash(text)) % 10_000_000}"

                yield Joke(
                    text=text,
                    source_name=f"tg/{channel}",
                    source_url=url,
                    external_id=external_id,
                    content_hash=build_hash(text),
                    source_views=views,
                )
                yielded += 1
                if yielded >= limit:
                    break

            if yielded == 0:
                logger.info("No jokes parsed from t.me/s/%s", channel)

            time.sleep(1)
