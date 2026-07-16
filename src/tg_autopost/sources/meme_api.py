import hashlib
import logging
import random
import re
from typing import Iterable

import requests

from ..models import Joke
from .base import JokeSource

logger = logging.getLogger(__name__)

# Cyrillic character range
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def _has_cyrillic(text: str) -> bool:
    """Check if text contains at least one Cyrillic character."""
    return bool(_CYRILLIC_RE.search(text))


class MemeApiSource(JokeSource):
    name = "meme_api"

    API_URLS = [
        "https://meme-api.com/gimme",  # random — may have some Russian
    ]

    def fetch(self, limit: int) -> Iterable[Joke]:
        fetched = 0
        attempts = 0
        max_attempts = limit * 10  # generous since most memes are English
        while fetched < limit and attempts < max_attempts:
            attempts += 1
            url = random.choice(self.API_URLS)
            try:
                resp = requests.get(url, timeout=15)
                data = resp.json()
                img_url = data.get("url") or data.get("preview", [None])[-1]
                title = data.get("title", "")
                post_link = data.get("postLink", "")
                if not img_url:
                    continue
                ext = img_url.rsplit(".", 1)[-1].lower()
                if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                    continue
                # Only keep memes with Russian text
                if not _has_cyrillic(title):
                    continue
                text = f"MEME:{img_url}\n{title}"
                h = hashlib.sha256(text.encode()).hexdigest()[:16]
                yield Joke(
                    text=text,
                    source_name=self.name,
                    source_url=post_link or img_url,
                    external_id=str(data.get("postLink", img_url)),
                    content_hash=h,
                )
                fetched += 1
            except Exception as e:
                logger.warning("meme_api fetch failed: %s", e)
