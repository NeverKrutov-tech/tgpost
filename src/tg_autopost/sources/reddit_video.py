import hashlib
import logging
import random
from typing import Iterable

import requests

from ..models import Joke
from .base import JokeSource

logger = logging.getLogger(__name__)

SUBREDDITS = [
    "funny",
    "memes",
    "dankmemes",
    "perfectlycutscreams",
    "ContagiousLaughter",
    "maybemaybemaybe",
    "Whatcouldgowrong",
    "nonononoyes",
    "AnimalsBeingDerps",
    "Unexpected",
]


class RedditVideoSource(JokeSource):
    name = "reddit_video"

    def fetch(self, limit: int) -> Iterable[Joke]:
        fetched = 0
        attempts = 0
        max_attempts = max(limit * 5, 20)
        while fetched < limit and attempts < max_attempts:
            attempts += 1
            sub = random.choice(SUBREDDITS)
            try:
                resp = requests.get(
                    f"https://www.reddit.com/r/{sub}/hot.json?limit=30",
                    headers={"User-Agent": "tgpost/1.0"},
                    timeout=15,
                )
                data = resp.json()
                children = data.get("data", {}).get("children", [])
                if not children:
                    continue
                random.shuffle(children)
                for child in children:
                    d = child.get("data", {})
                    if not d.get("is_video"):
                        continue
                    reddit_video = (d.get("media") or {}).get("reddit_video") or {}
                    video_url = reddit_video.get("fallback_url")
                    if not video_url:
                        continue
                    title = (d.get("title") or "")[:200]
                    post_link = "https://www.reddit.com" + d.get("permalink", "")
                    ext = video_url.rsplit(".", 1)[-1].lower()
                    if ext not in ("mp4",):
                        continue
                    text = f"VIDEO:{video_url}\n{title}"
                    h = hashlib.sha256(text.encode()).hexdigest()[:16]
                    yield Joke(
                        text=text,
                        source_name=self.name,
                        source_url=post_link,
                        external_id=d.get("id", video_url),
                        content_hash=h,
                    )
                    fetched += 1
                    if fetched >= limit:
                        break
            except Exception as e:
                logger.warning("reddit_video fetch %s failed: %s", sub, e)
