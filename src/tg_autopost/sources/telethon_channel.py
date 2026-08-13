import logging
import re
from typing import Iterable

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Message

from ..content_filter import is_flagged, is_ad
from ..models import Joke
from ..utils import build_hash, normalize_text
from .base import JokeSource

logger = logging.getLogger(__name__)

SKIP_PATTERNS = [
    re.compile(r"https?://", re.I),
    re.compile(r"@\w+"),
    re.compile(r"tg://"),
    re.compile(r"t\.me/"),
    re.compile(r"^\d+$"),
]

MIN_LENGTH = 30
MAX_LENGTH = 3000


class TelethonChannelSource(JokeSource):
    name = "telegram"

    def __init__(
        self,
        api_id: int,
        api_hash: str,
        session_string: str,
        channels: list[str],
        timeout: int = 20,
    ) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_string = session_string
        self.channels = [ch.lstrip("@") for ch in channels if ch.strip()]
        self.timeout = timeout

    def _is_joke_message(self, msg: Message) -> str | None:
        text = msg.text or msg.message or ""
        text = text.strip()
        if not text or len(text) < MIN_LENGTH or len(text) > MAX_LENGTH:
            return None
        if any(p.search(text) for p in SKIP_PATTERNS):
            return None
        if is_ad(text):
            return None
        normalized = normalize_text(text)
        if not normalized or len(normalized) < MIN_LENGTH:
            return None
        return normalized

    def fetch(self, limit: int) -> Iterable[Joke]:
        if not self.channels:
            return
        client = TelegramClient(
            StringSession(self.session_string),
            self.api_id,
            self.api_hash,
            timeout=self.timeout,
        )
        client.start()
        yielded = 0
        try:
            for channel in self.channels:
                if yielded >= limit:
                    break
                try:
                    entity = client.get_entity(channel)
                except Exception:
                    logger.warning("Failed to resolve channel %s", channel)
                    continue
                try:
                    messages = client.iter_messages(entity, limit=min(limit * 2, 100))
                    for msg in messages:
                        if yielded >= limit:
                            break
                        if msg.media:
                            continue
                        text = self._is_joke_message(msg)
                        if text is None:
                            continue
                        ext_id = f"tg_{channel}_{msg.id}"
                        yield Joke(
                            text=text,
                            source_name=f"tg/{channel}",
                            source_url=f"https://t.me/{channel}/{msg.id}",
                            external_id=ext_id,
                            content_hash=build_hash(text),
                        )
                        yielded += 1
                except Exception:
                    logger.exception("Failed to fetch messages from %s", channel)
        finally:
            client.disconnect()

        if yielded == 0:
            logger.info("No jokes parsed from Telegram channels via Telethon")