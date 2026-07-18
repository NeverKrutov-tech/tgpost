import json
import logging
import random
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional

import requests

from .database import Database
from .rubrics import RUBRICS

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

_SEEN_NEWS_FILE = "data/newsjacker_seen.json"


def _load_seen_news() -> set:
    try:
        data = Path(_SEEN_NEWS_FILE).read_text(encoding="utf-8")
        return set(json.loads(data))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def _save_seen_news(seen: set) -> None:
    Path(_SEEN_NEWS_FILE).write_text(
        json.dumps(list(seen)[-200:], ensure_ascii=False), encoding="utf-8"
    )


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


def _best_rubric(text: str) -> Optional[dict]:
    text_lower = text.lower()
    best = None
    best_score = 0
    for r in RUBRICS:
        score = sum(1 for kw in r["keywords"] if kw.lower() in text_lower)
        if score > best_score:
            best_score = score
            best = r
    return best


def _find_joke(db: Database, keywords: List[str]) -> Optional[tuple]:
    if not keywords:
        return None
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT text, content_hash FROM jokes WHERE published_at IS NULL ORDER BY RANDOM() LIMIT 300"
        ).fetchall()
    candidates = []
    for row in rows:
        text_lower = row["text"].lower()
        match_count = sum(1 for kw in keywords if kw.lower() in text_lower)
        if match_count >= 2:
            candidates.append((match_count, row["text"], row["content_hash"]))
    if not candidates:
        for row in rows:
            text_lower = row["text"].lower()
            match_count = sum(1 for kw in keywords if kw.lower() in text_lower)
            if match_count >= 1:
                candidates.append((match_count, row["text"], row["content_hash"]))
    if not candidates:
        return None
    candidates.sort(key=lambda x: -x[0])
    return (candidates[0][1], candidates[0][2])


def make_newsjacker_post(db: Database) -> Optional[str]:
    news_list = _fetch_news()
    if not news_list:
        logger.info("No news fetched")
        return None

    seen = _load_seen_news()
    unseen = [n for n in news_list if n["title"] not in seen]
    if not unseen:
        logger.info("All news already seen")
        return None

    item = random.choice(unseen[:10])
    title = item["title"]
    link = item.get("link", "")

    rubric = _best_rubric(title)
    title_kw = _extract_keywords(title)
    all_keywords = list(set((rubric["keywords"] if rubric else []) + title_kw))

    if not all_keywords:
        logger.info("No keywords for: %s", title)
        return None

    result = _find_joke(db, all_keywords)
    if not result:
        logger.info("No matching joke for: %s", title)
        return None

    joke_text, content_hash = result
    db.mark_published(content_hash)

    seen.add(title)
    _save_seen_news(seen)

    emoji = rubric["emoji"] if rubric else "📰"
    return f"{emoji} <b>{title}</b>\n<a href='{link}'>{link}</a>\n\nА вот и анекдот в тему:\n\n{joke_text}"
