import logging
import random
import time
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from ..models import Joke
from ..utils import build_hash, normalize_text
from .base import JokeSource

logger = logging.getLogger(__name__)

MIN_ID = 1
MAX_ID = 1000


class BaneksRuSource(JokeSource):
    name = "baneks.ru"

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout

    def _fetch_id(self, joke_id: int) -> str | None:
        url = f"https://baneks.ru/{joke_id}"
        try:
            resp = requests.get(url, timeout=self.timeout, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "html.parser")
            article = soup.select_one("article p")
            if article is None:
                return None
            text = article.get_text(" ", strip=True)
            if not text:
                return None
            return normalize_text(text)
        except Exception:
            return None

    def fetch(self, limit: int) -> Iterable[Joke]:
        ids = list(range(MIN_ID, MAX_ID + 1))
        random.shuffle(ids)
        yielded = 0
        for joke_id in ids:
            if yielded >= limit:
                break
            text = self._fetch_id(joke_id)
            if text is None:
                continue
            yield Joke(
                text=text,
                source_name=self.name,
                source_url=f"https://baneks.ru/{joke_id}",
                external_id=f"baneks_{joke_id}",
                content_hash=build_hash(text),
            )
            yielded += 1
            time.sleep(0.3)

        if yielded == 0:
            logger.warning("No jokes parsed from baneks.ru")