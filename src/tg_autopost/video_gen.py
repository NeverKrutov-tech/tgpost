import logging
import re
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoClip, AudioFileClip, CompositeVideoClip, TextClip, ColorClip, vfx

from .image_gen import FONT_PATH

logger = logging.getLogger(__name__)

W = 720
H = 1280
_BG_COLOR = (30, 30, 40)
_TEXT_COLOR = (240, 240, 240)
_DURATION = 10


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> str:
    words = text.split()
    lines = []
    cur = ""
    for w in words:
        test = cur + " " + w if cur else w
        bbox = font.getbbox(test)
        tw = bbox[2] - bbox[0]
        if tw > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def _make_text_image(text: str, font_size: int = 48) -> np.ndarray:
    padding = 40
    font = ImageFont.truetype(str(FONT_PATH), font_size)
    max_w = W - padding * 2
    wrapped = _wrap_text(text, font, max_w)
    lines = wrapped.count("\n") + 1
    line_h = font.getbbox("Ay")[3] - font.getbbox("Ay")[1]
    text_h = lines * (line_h + 8) + padding * 2
    text_h = min(text_h, H - 200)
    img = Image.new("RGBA", (W, text_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    y = padding
    for line in wrapped.split("\n"):
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (W - lw) // 2
        draw.text((x, y), line, font=font, fill=_TEXT_COLOR)
        y += line_h + 8
    return np.array(img)


def _background_frame(t: float) -> np.ndarray:
    progress = t / _DURATION
    r = int(_BG_COLOR[0] + progress * 20)
    g = int(_BG_COLOR[1] + progress * 15)
    b = int(_BG_COLOR[2] + progress * 25)
    bg = np.zeros((H, W, 3), dtype=np.uint8)
    bg[:, :] = [min(r, 255), min(g, 255), min(b, 255)]
    # subtle radial gradient
    cy, cx = H // 2, W // 2
    for y in range(H):
        dy = y - cy
        for x in range(W):
            dx = x - cx
            dist = np.sqrt(dx * dx + dy * dy) / max(H, W)
            fade = 1.0 - dist * 0.2
            bg[y, x] = [min(255, int(bg[y, x][0] * fade)),
                         min(255, int(bg[y, x][1] * fade)),
                         min(255, int(bg[y, x][2] * fade))]
    return bg


def _clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw)
    text = re.sub(r"#\w+", "", text)
    text = re.sub(r"@\w+", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = text.strip()
    max_len = 300
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


def generate_video(joke_text: str, music_path: str | None = None) -> str:
    text = _clean_text(joke_text)
    if not text:
        raise ValueError("Empty text after cleaning")

    font_sizes = [56, 48, 40, 36]
    for fs in font_sizes:
        text_img = _make_text_image(text, fs)
        if text_img.shape[0] <= H - 200:
            break

    def make_frame(t):
        frame = _background_frame(t)
        oh = text_img.shape[0]
        ow = text_img.shape[1]
        x = (W - ow) // 2
        y = (H - oh) // 2
        for c in range(3):
            alpha = text_img[:, :, 3] / 255.0
            frame[y:y+oh, x:x+ow, c] = (frame[y:y+oh, x:x+ow, c] * (1 - alpha) +
                                          text_img[:, :, c] * alpha)
        return frame

    clip = VideoClip(make_frame, duration=_DURATION)
    clip = clip.with_fps(24)

    if music_path and Path(music_path).exists():
        try:
            audio = AudioFileClip(music_path)
            audio = audio.with_duration(_DURATION)
            audio = audio.with_effects([vfx.MultiplyVolume(0.3)])
            clip = clip.with_audio(audio)
        except Exception as e:
            logger.warning("Audio overlay failed: %s", e)

    out_dir = Path("data")
    out_dir.mkdir(exist_ok=True)
    out_path = str(out_dir / f"joke_video_{abs(hash(joke_text))}.mp4")

    clip.write_videofile(
        out_path,
        codec="libx264",
        audio_codec="aac",
        fps=24,
        preset="ultrafast",
        threads=1,
        logger=None,
    )
    clip.close()
    logger.info("Video saved: %s", out_path)
    return out_path
