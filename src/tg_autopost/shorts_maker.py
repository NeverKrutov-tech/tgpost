import logging
import subprocess
from pathlib import Path

from .image_gen import FONT_PATH

logger = logging.getLogger(__name__)

SHORTS_DIR = Path("data/shorts")
SHORTS_WIDTH = 1080
SHORTS_HEIGHT = 1920
SECONDS_PER_CHAR = 0.3
MIN_DURATION = 8
MAX_DURATION = 55


def _wrap_text(text: str, max_chars: int = 35) -> str:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        if len(current) + len(word) + 1 <= max_chars:
            current = f"{current} {word}".strip()
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return "\n".join(lines)


def render_short(joke_text: str, output_path: str) -> bool:
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)
    wrapped = _wrap_text(joke_text)
    char_count = len(joke_text)
    duration = max(MIN_DURATION, min(MAX_DURATION, int(char_count * SECONDS_PER_CHAR)))

    font = FONT_PATH or "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font_size = 48 if char_count < 100 else 42 if char_count < 200 else 36

    text_file = SHORTS_DIR / "text.txt"
    text_file.write_text(wrapped, encoding="utf-8")

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=0x1a1a2e:s={SHORTS_WIDTH}x{SHORTS_HEIGHT}:d={duration}",
        "-vf",
        f"drawtext=textfile={text_file}:fontcolor=white:fontsize={font_size}"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
        f":fontfile={font}"
        f":line_spacing=20:shadowcolor=black:shadowx=2:shadowy=2",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "23",
        output_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        logger.info("Rendered short: %s (%ds, %d chars)", output_path, duration, char_count)
        return True
    except subprocess.CalledProcessError as e:
        logger.error("FFmpeg failed: %s", e.stderr.decode() if e.stderr else str(e))
        return False
    except Exception as e:
        logger.exception("Failed to render short")
        return False


def upload_short(
    video_path: str,
    title: str,
    description: str,
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> str | None:
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        logger.error("google-api-python-client not installed")
        return None

    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        body = {
            "snippet": {
                "title": title[:100],
                "description": (description + "\n\n\u041F\u043E\u0434\u043F\u0438\u0441\u044B\u0432\u0430\u0439\u0441\u044F: https://t.me/Anetdodik").strip()[:5000],
                "tags": ["\u0430\u043D\u0435\u043A\u0434\u043E\u0442", "\u044E\u043C\u043E\u0440", "shorts", "\u0441\u043C\u0435\u0448\u043D\u043E\u0435"],
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )
        response = request.execute()
        video_id = response["id"]
        logger.info("Uploaded short: https://youtu.be/%s", video_id)
        return video_id
    except Exception as e:
        logger.exception("Failed to upload short")
        return None
