import logging
import time
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from ..models import Joke
from ..utils import build_hash, normalize_text
from .base import JokeSource


class AnekdotRuSource(JokeSource):
    name = "anekdot.ru"

    SECTIONS = [
        "day",
        "week",
        "month",
        "random",
        "best",
        "sega",
    ]

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout

    def _parse_page(self, url: str) -> list[Joke]:
        response = requests.get(url, timeout=self.timeout, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        jokes: list[Joke] = []
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
            source_url = f"https://www.anekdot.ru/{link.get('href').lstrip('/')}" if link else url
            jokes.append(Joke(
                text=text,
                source_name=self.name,
                source_url=source_url,
                external_id=external_id,
                content_hash=build_hash(text),
            ))
        return jokes

    def fetch(self, limit: int) -> Iterable[Joke]:
        base = "https://www.anekdot.ru/release/anekdot"
        yielded = 0

        for section in self.SECTIONS:
            if yielded >= limit:
                break
            for page_num in range(1, 11):
                if yielded >= limit:
                    break
                page_url = f"{base}/{section}/{page_num}/" if page_num > 1 else f"{base}/{section}/"
                try:
                    jokes = self._parse_page(page_url)
                except Exception:
                    logging.getLogger(__name__).warning("Failed to fetch %s", page_url)
                    break
                if not jokes:
                    break
                for joke in jokes:
                    if yielded >= limit:
                        break
                    yield joke
                    yielded += 1
                time.sleep(0.3)

        if yielded == 0:
            logging.getLogger(__name__).warning("No jokes parsed from anekdot.ru")
