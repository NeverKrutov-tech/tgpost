import logging
import random
import re
import xml.etree.ElementTree as ET
from typing import List, Optional

import requests

from .database import Database

logger = logging.getLogger(__name__)

_STOPWORDS = frozenset("""
и в на с по со из у о к до за от про для без через под над об во да не но а или
же бы лишь только также ещё уже вот этот это что как так тут там где когда
который которая которое которые
""".split())

_NEWS_RSS = [
    "https://lenta.ru/rss/news",
    "https://news.mail.ru/rss/",
    "https://tass.ru/rss/v2.xml",
]


def _extract_keywords(text: str) -> List[str]:
    words = re.findall(r"[а-яёa-z]{4,}", text.lower())
    return [w for w in words if w not in _STOPWORDS]


def _fetch_news(timeout: int = 15) -> List[dict]:
    items = []
    for url in _NEWS_RSS:
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.iter("item"):
                title = item.findtext("title", "")
                link = item.findtext("link", "")
                if title:
                    items.append({"title": title.strip(), "link": link.strip()})
        except Exception:
            logger.warning("Failed to fetch news from %s", url, exc_info=True)
    return items


def _find_joke_for_keywords(db: Database, keywords: List[str]) -> Optional[str]:
    if not keywords:
        return None
    with db.connect() as conn:
        for kw in keywords:
            pattern = f"%{kw}%"
            rows = conn.execute(
                "SELECT text FROM jokes WHERE published_at IS NOT NULL AND LOWER(text) LIKE LOWER(?) LIMIT 10",
                (pattern,),
            ).fetchall()
            if rows:
                return random.choice(rows)["text"]
    return None


def make_newsjacker_post(db: Database) -> Optional[str]:
    news_list = _fetch_news()
    if not news_list:
        logger.info("No news fetched")
        return None
    item = random.choice(news_list[:10])
    title = item["title"]
    link = item.get("link", "")
    keywords = _extract_keywords(title)
    if not keywords:
        logger.info("No keywords extracted from: %s", title)
        return None
    joke = _find_joke_for_keywords(db, keywords)
    if not joke:
        logger.info("No matching joke for: %s", title)
        return None
    return f"📰 <b>{title}</b>\n<a href='{link}'>{link}</a>\n\nА вот и анекдот в тему:\n\n{joke}"
