import logging

import requests

logger = logging.getLogger(__name__)

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"


def _call(api_key: str, endpoint: str, params: dict) -> dict | None:
    try:
        resp = requests.get(
            f"{YOUTUBE_API}/{endpoint}",
            params={**params, "key": api_key},
            timeout=15,
        )
        if not resp.ok:
            logger.warning("YouTube API error %s: %s", resp.status_code, resp.text)
            return None
        return resp.json()
    except Exception as e:
        logger.exception("YouTube API call failed: %s", e)
        return None


def get_channel_stats(api_key: str, channel_id: str) -> dict | None:
    data = _call(api_key, "channels", {
        "part": "statistics",
        "id": channel_id,
    })
    if not data or "items" not in data or not data["items"]:
        return None
    stats = data["items"][0]["statistics"]
    return {
        "subscribers": int(stats.get("subscriberCount", 0)),
        "views": int(stats.get("viewCount", 0)),
        "videos": int(stats.get("videoCount", 0)),
    }


def get_latest_videos(api_key: str, channel_id: str, limit: int = 5) -> list[dict]:
    data = _call(api_key, "search", {
        "part": "snippet",
        "channelId": channel_id,
        "order": "date",
        "maxResults": limit,
        "type": "video",
    })
    if not data or "items" not in data:
        return []
    videos = []
    for item in data["items"]:
        videos.append({
            "id": item["id"]["videoId"],
            "title": item["snippet"]["title"],
            "published_at": item["snippet"]["publishedAt"],
            "thumb": item["snippet"]["thumbnails"].get("high", {}).get("url", ""),
        })
    return videos
