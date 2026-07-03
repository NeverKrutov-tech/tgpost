import logging
import random
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

MUSIC_DIR = Path("data/music")

TRACKS = [
    {
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Monkeys%20Spinning%20Monkeys.mp3",
        "name": "Monkeys Spinning Monkeys",
    },
    {
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Carefree.mp3",
        "name": "Carefree",
    },
    {
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Fluffing%20a%20Duck.mp3",
        "name": "Fluffing a Duck",
    },
    {
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Funk%20Game%20Loop.mp3",
        "name": "Funk Game Loop",
    },
    {
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Groove%20Groove.mp3",
        "name": "Groove Groove",
    },
    {
        "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Happy%20Boy%20End%20Theme.mp3",
        "name": "Happy Boy End Theme",
    },
]


def ensure_music(min_tracks: int = 3) -> int:
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)

    existing = list(MUSIC_DIR.glob("*.mp3"))
    if len(existing) >= min_tracks:
        return len(existing)

    random.shuffle(TRACKS)
    count = 0
    for track in TRACKS:
        dest = MUSIC_DIR / f"{track['name'].replace(' ', '_')}.mp3"
        if dest.exists():
            count += 1
            continue
        try:
            resp = requests.get(track["url"], timeout=30)
            if resp.status_code == 200 and len(resp.content) > 10000:
                dest.write_bytes(resp.content)
                count += 1
                logger.info("Downloaded music track: %s (%d KB)", track["name"], len(resp.content) // 1024)
            if count >= min_tracks:
                break
        except Exception as e:
            logger.warning("Failed to download %s: %s", track["name"], e)

    return len(list(MUSIC_DIR.glob("*.mp3")))
