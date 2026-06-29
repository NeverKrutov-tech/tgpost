import logging
import subprocess
import random
import colorsys
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from .image_gen import FONT_PATH

logger = logging.getLogger(__name__)

SHORTS_DIR = Path("data/shorts")
BG_DIR = SHORTS_DIR / "bg"
W = 1080
H = 1920
FPS = 24
SECONDS_PER_CHAR = 0.25
TITLE_DURATION = 2.0
OUTRO_DURATION = 2.0
MIN_DURATION = 10
MAX_DURATION = 50

PALETTES = [
    [(0.60, 0.85, 0.90), (0.70, 0.50, 0.95)],
    [(0.05, 0.85, 0.85), (0.30, 0.55, 0.85)],
    [(0.80, 0.75, 0.85), (0.95, 0.45, 0.75)],
    [(0.12, 0.80, 0.80), (0.50, 0.60, 0.85)],
    [(0.00, 0.70, 0.85), (0.10, 0.80, 0.90)],
]


def _hsl_rgb(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def _wrap(text: str, max_chars: int = 32) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= max_chars:
            cur = f"{cur} {w}".strip()
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text]


def _make_bg_frames(palette, num_frames: int) -> None:
    BG_DIR.mkdir(parents=True, exist_ok=True)
    h1, s1, l1 = palette[0]
    h2, s2, l2 = palette[1]

    for i in range(num_frames):
        t = i / 2.0
        shift = t * 0.03
        ch1 = (h1 + shift) % 1.0
        ch2 = (h2 + shift) % 1.0
        c1 = _hsl_rgb(ch1, s1, l1)
        c2 = _hsl_rgb(ch2, s2, l2)

        img = Image.new("RGB", (W, H))
        draw = ImageDraw.Draw(img)
        for y in range(H):
            frac = y / H
            r = int(c1[0] + (c2[0] - c1[0]) * frac)
            g = int(c1[1] + (c2[1] - c1[1]) * frac)
            b = int(c1[2] + (c2[2] - c1[2]) * frac)
            draw.line([(0, y), (W, y)], fill=(r, g, b))
        img.save(BG_DIR / f"bg_{i:04d}.png")


def render_short(joke_text: str, output_path: str) -> bool:
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)

    lines = _wrap(joke_text)
    if not lines:
        return False

    char_count = len(joke_text)
    duration = max(MIN_DURATION, min(MAX_DURATION,
        int(char_count * SECONDS_PER_CHAR) + TITLE_DURATION + OUTRO_DURATION))
    punchline_idx = len(lines) - 1
    palette = random.choice(PALETTES)

    # Background keyframes (2 per second)
    bg_count = int(duration * 2) + 2
    _make_bg_frames(palette, bg_count)

    # Line timing
    line_starts = []
    cur = TITLE_DURATION
    for line in lines:
        line_starts.append(cur)
        read = max(0.8, len(line) * SECONDS_PER_CHAR)
        cur += read + 0.3

    font = FONT_PATH or "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    base_fs = 72 if char_count < 80 else 56 if char_count < 180 else 44
    punch_fs = base_fs + 16

    # Build drawtext filter string
    vf_parts = []

    for i, line in enumerate(lines):
        start = line_starts[i]
        end = duration - 0.5
        fs = punch_fs if i == punchline_idx else base_fs
        escaped = line.replace(":", "\\:").replace("'", "\\'").replace(",", "\\,")
        color = "yellow" if i == punchline_idx else "white"
        y_pos = (H - len(lines) * 110) // 2 + i * 110
        ft = (
            f"drawtext=text='{escaped}'"
            f":fontfile={font}"
            f":fontsize={fs}"
            f":fontcolor={color}@0"
            f":x=(w-text_w)/2"
            f":y={y_pos}"
            f":enable='between(t,{start},{end})'"
            f":alpha='if(lt(t,{start}+0.4),(t-{start})/0.4,1)'"
            f":shadowcolor=black@0.6"
            f":shadowx=3:shadowy=3"
        )
        vf_parts.append(ft)

    # Title
    title_vf = (
        "drawtext=text='\\xF0\\x9F\\xA4\\xA3 \\xD0\\x90\\xD0\\x9D\\xD0\\x95\\xD0\\x9A\\xD0\\x94\\xD0\\x9E\\xD0\\xA2'"
        f":fontfile={font}"
        ":fontsize=110"
        ":fontcolor=white@0"
        ":x=(w-text_w)/2"
        ":y=h/4"
        f":enable='between(t,0,{TITLE_DURATION})'"
        f":alpha='if(lt(t,0.4),t/0.4,if(gt(t,{TITLE_DURATION}-0.5),({TITLE_DURATION}-t)/0.5,1))'"
        ":shadowcolor=black@0.6"
        ":shadowx=3:shadowy=3"
    )
    vf_parts.append(title_vf)

    # Outro
    outro_start = duration - OUTRO_DURATION
    outro1 = (
        "drawtext=text='\\xF0\\x9F\\x94\\xA5 \\xD0\\x9F\\xD0\\x9E\\xD0\\x94\\xD0\\x9F\\xD0\\x98\\xD0\\xA8\\xD0\\x98\\xD0\\xA1\\xD0\\xAC'"
        f":fontfile={font}"
        ":fontsize=100"
        ":fontcolor=yellow@0"
        ":x=(w-text_w)/2"
        ":y=h/3"
        f":enable='between(t,{outro_start},{duration})'"
        f":alpha='if(lt(t,{outro_start}+0.4),(t-{outro_start})/0.4,1)'"
        ":shadowcolor=black@0.6"
        ":shadowx=3:shadowy=3"
    )
    outro2 = (
        "drawtext=text='@Anetdodik'"
        f":fontfile={font}"
        ":fontsize=70"
        ":fontcolor=white@0"
        ":x=(w-text_w)/2"
        f":y=h/3+140"
        f":enable='between(t,{outro_start},{duration})'"
        f":alpha='if(lt(t,{outro_start}+0.6),(t-{outro_start}-0.2)/0.4,1)'"
        ":shadowcolor=black@0.6"
        ":shadowx=3:shadowy=3"
    )
    vf_parts.append(outro1)
    vf_parts.append(outro2)

    vf_str = f"minterpolate=fps={FPS}:mi_mode=blend,{','.join(vf_parts)}"

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-pattern_type", "glob",
        "-i", str(BG_DIR / "bg_*.png"),
        "-vf", vf_str,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "22",
        "-movflags", "+faststart",
        "-t", str(duration),
        output_path,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        logger.info("Rendered short: %s (%ds, %d lines)", output_path, duration, len(lines))
        return True
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else ""
        logger.error("FFmpeg failed: %s", stderr[:1000])
        return False
    except Exception as e:
        logger.exception("Failed to render short")
        return False
    finally:
        if BG_DIR.exists():
            shutil.rmtree(BG_DIR)


def upload_short(
    video_path: str, title: str, description: str,
    refresh_token: str, client_id: str, client_secret: str,
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
                "description": (description + "\n\nПодпишись: https://t.me/Anetdodik").strip()[:5000],
                "tags": ["анекдот", "юмор", "shorts", "смешное"],
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
