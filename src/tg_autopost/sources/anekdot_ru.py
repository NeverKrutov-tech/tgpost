import logging
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from ..models import Joke
from ..utils import build_hash, normalize_text
from .base import JokeSource


class AnekdotRuSource(JokeSource):
    name = "anekdot.ru"
    base_url = "https://www.anekdot.ru/release/anekdot/day/"

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout

    def fetch(self, limit: int) -> Iterable[Joke]:
        response = requests.get(self.base_url, timeout=self.timeout, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        yielded = 0
        for item in soup.select("div.topicbox"):
            text_node = item.select_one("div.text")
            if text_node is None:
                continue

            raw_text = text_node.get_text("\n", strip=True)
            text = normalize_text(raw_text)
            if not text:
                continue

            link = item.select_one("a[href^='/id/']")
            external_id = link.get("href", "").strip("/") if link else build_hash(text)[:16]
            source_url = f"https://www.anekdot.ru/{link.get('href').lstrip('/')}" if link else self.base_url

            yield Joke(
                text=text,
                source_name=self.name,
                source_url=source_url,
                external_id=external_id,
                content_hash=build_hash(text),
            )
            yielded += 1
            if yielded >= limit:
                break

        if yielded == 0:
            logging.getLogger(__name__).warning("No jokes parsed from anekdot.ru")
