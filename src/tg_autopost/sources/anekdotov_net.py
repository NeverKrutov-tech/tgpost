import logging
import time
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from ..models import Joke
from ..utils import build_hash, normalize_text
from .base import JokeSource

logger = logging.getLogger(__name__)


class AnekdotovNetSource(JokeSource):
    name = "anekdotov.net"

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout

    def _parse_page(self, url: str) -> list[Joke]:
        response = requests.get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser", from_encoding="windows-1251")
        jokes: list[Joke] = []
        for div in soup.select("div.anekdot"):
            hidden = div.find("div", id=lambda x: x and x.startswith("1") and x[1:].replace(".", "", 1).isdigit())
            text = hidden.get_text(" ", strip=True) if hidden else div.get_text(" ", strip=True)
            text = normalize_text(text)
            if not text:
                continue
            jokes.append(Joke(
                text=text,
                source_name=self.name,
                source_url=url,
                external_id=build_hash(text)[:16],
                content_hash=build_hash(text),
            ))
        return jokes

    def fetch(self, limit: int) -> Iterable[Joke]:
        base = "https://anekdotov.net/anekdot"
        yielded = 0

        for page_num in range(1, 51):
            if yielded >= limit:
                break
            page_url = f"{base}/page/{page_num}/" if page_num > 1 else f"{base}/"
            try:
                jokes = self._parse_page(page_url)
            except Exception:
                try:
                    page_url = f"{base}/page{page_num}.html" if page_num > 1 else f"{base}/"
                    jokes = self._parse_page(page_url)
                except Exception:
                    logger.warning("Failed to fetch %s", page_url)
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
            logger.warning("No jokes parsed from anekdotov.net")
