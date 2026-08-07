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

# ponytail: almost every channel signs its posts with @username or a t.me link.
# Rejecting those threw away most of the good jokes, so strip the signature
# instead and judge what is left.
NOISE_PATTERNS = [
    re.compile(r"https?://\S+", re.I),
    re.compile(r"tg://\S+", re.I),
    re.compile(r"\bt\.me/\S+", re.I),
    re.compile(r"@[A-Za-z]\w{3,}"),
    re.compile(r"#\w+"),
]

# Only drop the post outright when there is no joke to salvage.
SKIP_PATTERNS = [
    re.compile(r"^\d+$"),
]


def strip_noise(text: str) -> str:
    """Remove channel signatures, links and hashtags, keep the joke."""
    for pattern in NOISE_PATTERNS:
        text = pattern.sub(" ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    # Trailing lines that were pure signature are now empty - drop them.
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    return "\n".join(lines)

# ponytail: "подпишись" alone is just a channel signature, not an ad - it gets
# stripped by strip_noise. Only phrases that mean the post itself is an ad or
# a teaser stay here.
AD_PHRASES = [
    "\u0447\u0438\u0442\u0430\u0442\u044C \u043F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435",
    "\u0447\u0438\u0442\u0430\u0439\u0442\u0435 \u043F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435",
    "\u043F\u0440\u043E\u0434\u043E\u043B\u0436\u0435\u043D\u0438\u0435 \u0432",
    "\u0440\u0435\u043A\u043B\u0430\u043C\u0430",
    "\u0440\u0435\u043A\u043B\u0430\u043C\u043D\u044B\u0439 \u043F\u043E\u0441\u0442",
    "\u0435\u0440\u0438\u0434",
    "\u0440\u0435\u0444. \u0441\u0441\u044B\u043B\u043A\u0430",
    "\u043F\u0440\u043E\u043C\u043E\u043A\u043E\u0434",
    "\u0441\u043A\u0438\u0434\u043A\u0430 \u043F\u043E \u043F\u0440\u043E\u043C\u043E\u043A\u043E\u0434\u0443",
]

CYRILLIC_RE = re.compile(r"[\u0430-\u044F\u0451]", re.I)

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
                if not raw_text or len(raw_text) > MAX_LENGTH:
                    continue

                raw_lower = raw_text.lower()
                if any(phrase in raw_lower for phrase in AD_PHRASES):
                    continue

                # Strip the channel signature first, then judge what remains.
                raw_text = strip_noise(raw_text)
                if any(p.search(raw_text) for p in SKIP_PATTERNS):
                    continue

                text = normalize_text(raw_text)
                if not text or len(text) < MIN_LENGTH:
                    continue
                # Russian channel: drop posts that are not actually Russian.
                if len(CYRILLIC_RE.findall(text)) < len(text) * 0.3:
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
