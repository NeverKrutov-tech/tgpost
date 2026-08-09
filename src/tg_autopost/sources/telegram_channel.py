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

# ponytail: re-posting channels sign the joke with a bare channel name on the
# last line ("Хохотун", "Жиза", "Смех") - no @, no link, so NOISE_PATTERNS
# miss it and it ships to the channel as if it were part of the joke. It is
# only safe to cut when the line is a standalone short word that cannot be a
# punchline: a punchline either ends in punctuation or is a dialogue reply
# (starts with "-"). A bare last word with no terminator is a signature.
_CHANNEL_SIG_END_RE = re.compile(
    r"[\w\u0400-\u04FF\u2014-]+(?:\s+[\w\u0400-\u04FF\u2014-]+)?\s*$"
)


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

    # Drop pure-decoration lines at the edges (emoji dividers, the "-" that
    # survives a "— @channel" signature) - nothing but emoji/punctuation
    # cannot be part of the joke. Never touch interior lines.
    def _has_word(line: str) -> bool:
        return any(ch.isalnum() for ch in line)

    while lines and not _has_word(lines[-1]):
        lines.pop()
    while lines and not _has_word(lines[0]):
        lines.pop(0)

    # Drop a final bare-name channel signature (see comment above). Only
    # when there is more than one line: a single-line aphorism IS the whole
    # joke and must not be mistaken for a signature.
    if len(lines) > 1:
        while lines:
            last = lines[-1]
            if not last:
                lines.pop()
                continue
            if last.startswith(("-", "\u2014", "\u2013")):
                break
            if re.search(r"[.!?…:»\")\]]\s*$", last):
                break
            if re.fullmatch(
                r"[\w\u0400-\u04FF\u2014'-]+(?:\s+[\w\u0400-\u04FF\u2014'-]+)?",
                last,
            ):
                lines.pop()
                continue
            break

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


def _parse_subscribers(soup) -> int:
    count_el = soup.select_one("div.tgme_channel_info_count")
    if count_el is None:
        return 0
    text = count_el.get_text(" ", strip=True)
    # "2 600 subscribers", "2.6K subscribers", "1.2М подписчиков"
    match = re.search(r"([\d]+(?:[\s.,][\d]+)*)\s*([KkМм]?)\s*(?:subscribers?\b|подписчик\w*)", text)
    if not match:
        return 0
    num_str = match.group(1).replace("\u00A0", "").replace(",", "").replace(" ", "")
    num = float(num_str)
    suffix = match.group(2).lower()
    if suffix in ("k", "к"):
        num *= 1000
    elif suffix in ("m", "м"):
        num *= 1_000_000
    return int(num)


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
            subscribers = _parse_subscribers(soup)
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
                    channel_name=channel,
                    channel_subscribers=subscribers,
                )
                yielded += 1
                if yielded >= limit:
                    break

            if yielded == 0:
                logger.info("No jokes parsed from t.me/s/%s", channel)

            time.sleep(1)
