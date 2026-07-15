import logging

import requests

logger = logging.getLogger(__name__)


def post_to_vk(vk_token: str, owner_id: int, message: str) -> bool:
    if not vk_token:
        return False
    try:
        url = "https://api.vk.com/method/wall.post"
        resp = requests.post(url, data={
            "access_token": vk_token,
            "owner_id": owner_id,
            "message": message,
            "from_group": 1,
            "v": "5.199",
        }, timeout=15)
        data = resp.json()
        if data.get("response", {}).get("post_id"):
            logger.info("Posted to VK: post_id=%s", data["response"]["post_id"])
            return True
        logger.warning("VK API error: %s", data)
        return False
    except Exception as e:
        logger.exception("VK post failed: %s", e)
        return False
