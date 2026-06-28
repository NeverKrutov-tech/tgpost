import logging
from typing import Iterable

import requests
from bs4 import BeautifulSoup

from ..models import Joke
from ..utils import build_hash, normalize_text
from .base import JokeSource

logger = logging.getLogger(__name__)


class AnekdotovNetSource(JokeSource):
    name = "anekdotov.net"
    base_url = "https://anekdotov.net/anekdot/"

    def __init__(self, timeout: int = 20) -> None:
        self.timeout = timeout

    def fetch(self, limit: int) -> Iterable[Joke]:
        response = requests.get(
            self.base_url,
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.content, "html.parser", from_encoding="windows-1251")

        yielded = 0
        for div in soup.select("div.anekdot"):
            hidden = div.find("div", id=lambda x: x and x.startswith("1") and x[1:].replace(".", "", 1).isdigit())
            text = hidden.get_text(" ", strip=True) if hidden else div.get_text(" ", strip=True)
            text = normalize_text(text)

            if not text:
                continue

            yield Joke(
                text=text,
                source_name=self.name,
                source_url=self.base_url,
                external_id=build_hash(text)[:16],
                content_hash=build_hash(text),
            )
            yielded += 1
            if yielded >= limit:
                break

        if yielded == 0:
            logger.warning("No jokes parsed from anekdotov.net")
