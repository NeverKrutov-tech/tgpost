import logging
import math
import os
import random
import struct
import subprocess
import colorsys
import shutil
import asyncio
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

from .image_gen import FONT_PATH

logger = logging.getLogger(__name__)

SHORTS_DIR = Path("data/shorts")
MUSIC_DIR = Path("data/music")
W, H = 1080, 1920
FPS = 24

PALETTES = [
    [(0.60, 0.85, 0.90), (0.70, 0.50, 0.95)],
    [(0.05, 0.85, 0.85), (0.30, 0.55, 0.85)],
    [(0.80, 0.75, 0.85), (0.95, 0.45, 0.75)],
    [(0.12, 0.80, 0.80), (0.50, 0.60, 0.85)],
    [(0.00, 0.70, 0.85), (0.10, 0.80, 0.90)],
    [(0.50, 0.90, 0.50), (0.55, 0.90, 0.50)],
]

SPEAKER_EMOJIS = ["\U0001f9d1", "\U0001f468\u200d\U00002694\ufe0f"]
BUBBLE_COLORS = [(50, 70, 120), (80, 50, 100)]
BUBBLE_ALIGN = ["left", "right"]


def _hsl_rgb(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    path = FONT_PATH or "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(str(path), size)


def _theme_emoji(joke_text: str) -> str:
    text = joke_text.lower()
    if any(w in text for w in ["\u0432\u0440\u0430\u0447", "\u0431\u043E\u043B\u044C\u043D\u0438\u0446\u0430"]):
        return "\U0001fa7a"
    if any(w in text for w in ["\u0440\u0430\u0431\u043E\u0442\u0430", "\u043E\u0444\u0438\u0441", "\u0448\u0435\u0444"]):
        return "\U0001f3e2"
    if any(w in text for w in ["\u043C\u0443\u0436", "\u0436\u0435\u043D", "\u0441\u0435\u043C\u044C", "\u0442\u0435\u0449"]):
        return "\U0001f3e1"
    if any(w in text for w in ["\u0430\u0440\u043C\u0438", "\u0432\u043E\u0435\u043D", "\u0441\u043E\u043B\u0434\u0430\u0442"]):
        return "\U0001f396\ufe0f"
    if any(w in text for w in ["\u043F\u043E\u043B\u0438\u0446", "\u0433\u0430\u0438"]):
        return "\U0001f6a8"
    if any(w in text for w in ["\u0432\u043E\u0434\u043A\u0430", "\u043F\u0438\u0432\u043E", "\u0431\u0430\u0440"]):
        return "\U0001f37a"
    if any(w in text for w in ["\u0448\u043A\u043E\u043B", "\u0443\u0447\u0438\u0442\u0435\u043B", "\u0443\u0440\u043E\u043A"]):
        return "\U0001f393"
    if any(w in text for w in ["\u043A\u043E\u0442", "\u043A\u043E\u0448\u043A", "\u0441\u043E\u0431\u0430\u043A"]):
        return "\U0001f431"
    return "\U0001f4ac"


TOPIC_PROMPTS: list[tuple[list[str], str]] = [
    (["\u0440\u0430\u0431\u043E\u0442\u0430", "\u043E\u0444\u0438\u0441", "\u0448\u0435\u0444", "\u043D\u0430\u0447\u0430\u043B\u044C\u043D\u0438\u043A", "\u043A\u043E\u043B\u043B\u0435\u0433", "\u0434\u0438\u0440\u0435\u043A\u0442\u043E\u0440"], "\u0440\u0430\u0431\u043E\u0442\u0430"),
    (["\u0432\u0440\u0430\u0447", "\u0431\u043E\u043B\u044C\u043D\u0438\u0446\u0430", "\u0445\u0438\u0440\u0443\u0440\u0433", "\u043F\u0430\u0446\u0438\u0435\u043D\u0442", "\u0430\u043F\u0442\u0435\u043A\u0430"], "\u0432\u0440\u0430\u0447"),
    (["\u043C\u0443\u0436", "\u0436\u0435\u043D", "\u0441\u0435\u043C\u044C", "\u0442\u0435\u0449", "\u0441\u0432\u0435\u043A\u0440\u043E\u0432", "\u0436\u0435\u043D\u0430", "\u0442\u0451\u0449"], "\u0441\u0435\u043C\u044C"),
    (["\u0430\u0440\u043C\u0438", "\u0432\u043E\u0435\u043D", "\u0441\u043E\u043B\u0434\u0430\u0442", "\u043F\u043E\u043B\u043A\u043E\u0432\u043D\u0438\u043A", "\u043A\u0430\u0437\u0430\u0440\u043C"], "\u0430\u0440\u043C\u0438"),
    (["\u043C\u0438\u043B\u0438\u0446", "\u043F\u043E\u043B\u0438\u0446", "\u0433\u0430\u0438", "\u0433\u0430\u0438\u0448\u043D\u0438\u043A"], "\u043C\u0438\u043B\u0438\u0446"),
    (["\u0432\u043E\u0434\u043A\u0430", "\u043F\u0438\u0432\u043E", "\u0431\u0430\u0440", "\u043F\u044C\u044F\u043D", "\u0432\u044B\u043F\u0438\u0432"], "\u0432\u043E\u0434\u043A\u0430"),
    (["\u0448\u043A\u043E\u043B", "\u0443\u0447\u0438\u0442\u0435\u043B", "\u0443\u0440\u043E\u043A", "\u043A\u043B\u0430\u0441\u0441", "\u0443\u0447\u0435\u043D\u0438\u043A"], "\u0448\u043A\u043E\u043B"),
    (["\u043A\u043E\u0442", "\u043A\u043E\u0448\u043A", "\u0441\u043E\u0431\u0430\u043A", "\u0437\u043E\u043E\u043F\u0430\u0440\u043A", "\u043C\u0435\u0434\u0432\u0435\u0434"], "\u043A\u043E\u0442"),
    (["\u0440\u0435\u0441\u0442\u043E\u0440\u0430\u043D", "\u0435\u0434\u0430", "\u043E\u0431\u0435\u0434", "\u0433\u043E\u0442\u043E\u0432"], "\u0440\u0435\u0441\u0442\u043E\u0440\u0430\u043D"),
    (["\u0434\u0435\u043D\u044C\u0433", "\u0431\u0430\u043D\u043A", "\u043E\u043B\u0438\u0433\u0430\u0440\u0445", "\u0431\u0438\u0437\u043D\u0435\u0441", "\u043C\u0438\u043B\u043B\u0438\u043E\u043D"], "\u0434\u0435\u043D\u044C\u0433"),
]

THEME_SCENES = {
    "\u0440\u0430\u0431\u043E\u0442\u0430": "modern office interior with desks, soft natural lighting, professional atmosphere",
    "\u0432\u0440\u0430\u0447": "clean hospital corridor, medical equipment, white walls, clinical lighting",
    "\u0441\u0435\u043C\u044C": "cozy home living room, warm lamp light, comfortable armchair, fireplace",
    "\u0430\u0440\u043C\u0438": "military barracks, camouflage nets, morning sunlight, army atmosphere",
    "\u043C\u0438\u043B\u0438\u0446": "police station interior, desk with papers, blue uniform, official atmosphere",
    "\u0432\u043E\u0434\u043A\u0430": "russian pub interior, wooden tables, dim warm lighting, rustic atmosphere",
    "\u0448\u043A\u043E\u043B": "empty classroom, wooden desks, chalkboard, sunlight through window",
    "\u043A\u043E\u0442": "sunlit room with a sleeping cat on a windowsill, peaceful atmosphere",
    "\u0440\u0435\u0441\u0442\u043E\u0440\u0430\u043D": "elegant restaurant interior, candlelit tables, warm amber lighting",
    "\u0434\u0435\u043D\u044C\u0433": "luxury office interior, modern furniture, city view through window",
}

DEFAULT_PROMPT = "cozy interior room, warm lighting, comfortable atmosphere, cinematic, highly detailed, 4k"


def _guess_theme(joke_text: str) -> str:
    text = joke_text.lower()
    for words, theme_key in TOPIC_PROMPTS:
        for w in words:
            if w in text:
                return THEME_SCENES.get(theme_key, DEFAULT_PROMPT)
    return DEFAULT_PROMPT


def _generate_background(joke_text: str, cf_id: str = "", cf_token: str = "", hf_token: str = "") -> Image.Image | None:
    prompt = _guess_theme(joke_text)
    full_prompt = f"{prompt}, vertical portrait orientation, no text, no people, 4k"

    def _open(img_data) -> Image.Image | None:
        try:
            img = Image.open(BytesIO(img_data)).convert("RGB")
            return img.resize((W, H), Image.Resampling.BILINEAR)
        except Exception:
            return None

    if cf_id and cf_token:
        try:
            url = f"https://api.cloudflare.com/client/v4/accounts/{cf_id}/ai/run/@cf/stabilityai/stable-diffusion-xl-base-1.0"
            resp = requests.post(url, headers={"Authorization": f"Bearer {cf_token}", "Accept": "application/json"}, json={"prompt": full_prompt}, timeout=30)
            if resp.status_code == 200:
                ct = resp.headers.get("content-type", "")
                if "image" in ct:
                    img = _open(resp.content)
                    if img:
                        logger.info("Generated background via Cloudflare SDXL (raw): %s", prompt)
                        return img
                else:
                    try:
                        data = resp.json()
                        if data.get("success"):
                            import base64
                            img_bytes = base64.b64decode(data["result"]["image"])
                            img = _open(img_bytes)
                            if img:
                                logger.info("Generated background via Cloudflare SDXL (json): %s", prompt)
                                return img
                        logger.warning("Cloudflare API returned success=false: %s", str(data.get("errors", ""))[:150])
                    except Exception:
                        logger.warning("Cloudflare response not JSON (%s), len=%d", ct, len(resp.content))
            else:
                logger.warning("Cloudflare API status %d: %s", resp.status_code, resp.text[:300])
        except Exception as e:
            logger.warning("Cloudflare failed: %s", e)

    try:
        import urllib.parse
        url = f"https://image.pollinations.ai/prompt/{urllib.parse.quote(full_prompt)}?width=1080&height=1920&nofeed=true"
        resp = requests.get(url, timeout=90)
        if resp.status_code == 200:
            img = _open(resp.content)
            if img:
                logger.info("Generated background via pollinations: %s", prompt)
                return img
    except Exception as e:
        logger.warning("Pollinations failed: %s", e)

    if hf_token:
        for model_name, model_url in [
            ("stable-diffusion-v1-5", "https://api-inference.huggingface.co/models/runwayml/stable-diffusion-v1-5"),
            ("stable-diffusion-2-1", "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-2-1"),
        ]:
            try:
                hf_headers = {"Authorization": f"Bearer {hf_token}"}
                resp = requests.post(model_url, headers=hf_headers, json={"inputs": full_prompt}, timeout=90)
                if resp.status_code == 503:
                    import time
                    logger.warning("HF model loading (%s), waiting 15s...", model_name)
                    time.sleep(15)
                    resp = requests.post(model_url, headers=hf_headers, json={"inputs": full_prompt}, timeout=90)
                if resp.status_code == 200:
                    img = _open(resp.content)
                    if img:
                        logger.info("Generated background via HF %s: %s", model_name, prompt)
                        return img
            except Exception as e:
                logger.warning("HF %s failed: %s", model_name, e)

    logger.warning("All background APIs failed, using gradient fallback")
    return None


# ── Scene parsing ─────────────────────────────────────────

def _parse_scenes(joke_text: str) -> list[dict]:
    lines = joke_text.strip().split("\n")
    scenes = []
    dialogue_idx = 0
    narrative_buffer = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        is_dialogue = any(stripped.startswith(c) for c in ["\u2014", "-", "\u2013"])
        if is_dialogue:
            if narrative_buffer:
                scenes.append({"type": "narrative", "text": "\n".join(narrative_buffer)})
                narrative_buffer = []
            text = stripped.lstrip("\u2014- \u2013")
            scenes.append({"type": "dialogue", "text": text, "speaker": dialogue_idx % 2})
            dialogue_idx += 1
        else:
            narrative_buffer.append(stripped)

    if narrative_buffer:
        scenes.append({"type": "narrative", "text": "\n".join(narrative_buffer)})

    if scenes:
        scenes[-1]["type"] = "punchline"

    return scenes


# ── Audio ─────────────────────────────────────────────────

async def _edge_tts(text: str, output_path: Path) -> float:
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, "ru-RU-DariyaNeural")
        await communicate.save(str(output_path))
        if output_path.stat().st_size > 100:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                 str(output_path)],
                capture_output=True, text=True, timeout=15,
            )
            return float(result.stdout.strip())
    except Exception as e:
        logger.warning("edge-tts failed: %s", e)
    return 0.0


def _generate_tts(text: str, output_path: Path) -> float:
    dur = asyncio.run(_edge_tts(text, output_path))
    if dur > 0:
        logger.info("Generated TTS via edge-tts: %.1fs", dur)
        return dur

    logger.info("edge-tts failed, falling back to gTTS")
    try:
        from gtts import gTTS
        tts = gTTS(text=text, lang="ru", slow=False)
        tts.save(str(output_path))
        if output_path.stat().st_size > 100:
            try:
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries",
                     "format=duration", "-of", "default=noprint_wrappers=1:nokey=1",
                     str(output_path)],
                    capture_output=True, text=True, timeout=15,
                )
                return float(result.stdout.strip())
            except Exception:
                pass
        return len(text) * 0.08
    except Exception as e:
        logger.error("TTS failed: %s", e)
        output_path.write_text("")
        return len(text) * 0.08


def _select_music(total_dur: float, output_path: Path) -> bool:
    if not MUSIC_DIR.exists():
        return False
    tracks = list(MUSIC_DIR.glob("*.mp3")) + list(MUSIC_DIR.glob("*.wav"))
    if not tracks:
        return False
    track = random.choice(tracks)
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(track),
            "-filter_complex",
            f"aloop=loop=-1:size=44100*{int(min(30, total_dur))}[out];[out]volume=0.2[aout]",
            "-t", str(total_dur),
            "-map", "[aout]",
            "-acodec", "pcm_s16le",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        logger.info("Selected music track: %s", track.name)
        return True
    except Exception as e:
        logger.warning("Failed to process music track %s: %s", track.name, e)
        return False


def _generate_beat(duration: float, output_path: Path, bpm: int = 128, sr: int = 44100) -> None:
    beat_sec = 60.0 / bpm
    total_samples = int(duration * sr)
    samples = [0.0] * total_samples
    rng = random.Random(42)

    for i in range(total_samples):
        t = i / sr
        kick_phase = (t % beat_sec) / beat_sec
        if kick_phase < 0.08:
            env = math.exp(-kick_phase * 80)
            samples[i] += 0.45 * env * math.sin(2 * math.pi * 55 * (1 + 3 * kick_phase) * t)
        eighth = beat_sec / 2
        hat_phase = (t % eighth) / eighth
        if hat_phase < 0.04:
            env = math.exp(-hat_phase * 120)
            samples[i] += 0.12 * env * rng.gauss(0, 1)
        pad_note = 130.81
        if int(t // beat_sec) % 8 < 4:
            pad_freq = pad_note
        else:
            pad_freq = pad_note * 1.5
        pad_env = 0.06 * (1 - math.exp(-t * 0.5)) * max(0, 1 - (t / duration))
        samples[i] += pad_env * (
            0.5 * math.sin(2 * math.pi * pad_freq * t) +
            0.3 * math.sin(2 * math.pi * pad_freq * 2 * t)
        )

    peak = max(abs(s) for s in samples) or 1
    ints = [int(s / peak * 30000) for s in samples]

    with open(output_path, "wb") as f:
        data_size = len(ints) * 2
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        for s in ints:
            f.write(struct.pack("<h", s))

    logger.info("Generated beat: %.1fs, %s", duration, output_path)


# ── Frame rendering ───────────────────────────────────────

def _render_gradient_strip(palette, shift: float) -> Image.Image:
    h1, s1, l1 = palette[0]
    h2, s2, l2 = palette[1]
    ch1 = (h1 + shift) % 1.0
    ch2 = (h2 + shift) % 1.0
    c1 = _hsl_rgb(ch1, s1, l1)
    c2 = _hsl_rgb(ch2, s2, l2)

    img = Image.new("RGB", (1, H))
    pix = img.load()
    for y in range(H):
        frac = y / H
        r = int(c1[0] + (c2[0] - c1[0]) * frac)
        g = int(c1[1] + (c2[1] - c1[1]) * frac)
        b = int(c1[2] + (c2[2] - c1[2]) * frac)
        pix[0, y] = (r, g, b)
    return img


def _draw_rounded_rect(draw, x1, y1, x2, y2, radius, fill):
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)


def _draw_bubble(draw, text, x, y, width, align, bubble_color, font, max_width=800):
    padding = 30
    border_radius = 25
    tail_size = 20

    lines = []
    for word in text.split():
        if not lines:
            lines.append(word)
        elif draw.textbbox((0, 0), lines[-1] + " " + word, font=font)[2] - draw.textbbox((0, 0), lines[-1] + " " + word, font=font)[0] < max_width:
            lines[-1] += " " + word
        else:
            lines.append(word)

    line_height = draw.textbbox((0, 0), "Ag", font=font)[3] - draw.textbbox((0, 0), "Ag", font=font)[1] + 8
    text_h = len(lines) * line_height
    bw = min(max_width, max(draw.textbbox((0, 0), l, font=font)[2] - draw.textbbox((0, 0), l, font=font)[0] for l in lines) + padding * 2)
    bh = text_h + padding * 2

    if align == "right":
        bx = x - bw
        tail_points = [(x - 5, y + bh // 2), (x - 5 - tail_size, y + bh // 2 - 10), (x - 5 - tail_size, y + bh // 2 + 10)]
    else:
        bx = x
        tail_points = [(x + bw + 5, y + bh // 2), (x + bw + 5 + tail_size, y + bh // 2 - 10), (x + bw + 5 + tail_size, y + bh // 2 + 10)]

    _draw_rounded_rect(draw, bx, y, bx + bw, y + bh, border_radius, bubble_color)
    draw.polygon(tail_points, fill=bubble_color)

    for i, line in enumerate(lines):
        lx = bx + padding
        ly = y + padding + i * line_height
        draw.text((lx, ly), line, font=font, fill=(255, 255, 255, 255))

    return bh


def _draw_progress_bar(draw, t, total_dur):
    bar_h = 6
    bar_y = H - bar_h - 10
    bar_w = W - 80
    bar_x = 40
    progress = min(1.0, t / max(total_dur, 1))

    _draw_rounded_rect(draw, bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, 3, (255, 255, 255, 40))

    fill_w = int(bar_w * progress)
    if fill_w > 0:
        _draw_rounded_rect(draw, bar_x, bar_y, bar_x + fill_w, bar_y + bar_h, 3, (255, 215, 0, 200))


def _render_frame(t: float, total_dur: float,
                  scenes: list[dict], scene_times: list[tuple[float, float]],
                  palette: list, particles: list[dict],
                  background: Image.Image | None = None) -> Image.Image:
    shift = t * 0.02

    zoom = 1.0 + 0.04 * (t / max(total_dur, 1))
    zoom_w, zoom_h = int(W * zoom), int(H * zoom)
    cx, cy = zoom_w // 2 - W // 2, zoom_h // 2 - H // 2

    if background is not None:
        bg = background.copy()
        bg = bg.resize((zoom_w, zoom_h), Image.Resampling.BILINEAR)
        bg = bg.crop([cx, cy, cx + W, cy + H])
    else:
        strip = _render_gradient_strip(palette, shift)
        bg = strip.resize((W, H), Image.Resampling.BILINEAR)
    frame = bg.convert("RGBA")

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 50))
    draw = ImageDraw.Draw(overlay)

    for p in particles:
        px = (p["x"] + t * p["vx"]) % W
        py = (p["y"] + t * p["vy"]) % H
        phase = t * p["freq"] + p["phase"]
        alpha = int((0.3 + 0.7 * max(0, math.sin(phase))) * 100)
        r = p["radius"]
        draw.ellipse([px - r, py - r, px + r, py + r], fill=(255, 255, 255, alpha))

    visible_scenes = [(i, st, et) for i, (st, et) in enumerate(scene_times) if st <= t <= et]

    font = _get_font(56)
    punch_font = _get_font(72)

    for i, st, et in visible_scenes:
        scene = scenes[i]
        local_t = max(0, t - st)
        fade = min(1.0, local_t / 0.3)
        is_punch = scene.get("type") == "punchline"
        ttl_dur = max(0.5, et - st)
        char_speed = len(scene["text"]) / ttl_dur * 1.2
        chars_visible = min(len(scene["text"]), int(char_speed * local_t))

        if scene["type"] == "dialogue":
            speaker = scene.get("speaker", 0)
            emoji = SPEAKER_EMOJIS[speaker]
            align = BUBBLE_ALIGN[speaker]
            color = BUBBLE_COLORS[speaker]

            bubble_x = 80 if align == "left" else W - 80
            bubble_y = H // 2 - 100

            display_text = scene["text"][:chars_visible]
            if display_text:
                emoji_font = _get_font(80)
                eb = emoji_font.getbbox(emoji)
                ew = eb[2] - eb[0]
                emoji_x = bubble_x - ew // 2 if align == "left" else bubble_x - ew // 2
                emoji_y = bubble_y - 70
                draw.text((emoji_x, emoji_y), emoji, font=emoji_font, fill=(255, 255, 255, int(fade * 255)))

                _draw_bubble(draw, display_text, bubble_x, bubble_y, int(bubble_x if align == "left" else W - bubble_x), align, (*color, int(fade * 255)), font if not is_punch else punch_font)

                if is_punch:
                    sparkle = ["\u2728", "\u2b50", "\U0001f4a5"]
                    for j, s in enumerate(sparkle):
                        sx = random.randint(100, W - 100)
                        sy = random.randint(bubble_y - 80, bubble_y + 200)
                        sa = int(fade * 255 * max(0, (t - st) % 0.5 / 0.5))
                        if sa > 0:
                            draw.text((sx, sy), s, font=_get_font(40), fill=(255, 220, 50, sa))

        elif scene["type"] == "narrative":
            alpha = int(fade * 255)
            if alpha > 0:
                lines = scene["text"].split("\n")
                line_h = 70
                total = len(lines) * line_h
                start_y = (H - total) // 2

                for j, line in enumerate(lines):
                    y = start_y + j * line_h
                    lchars = min(len(line), max(0, int(char_speed * local_t) - sum(len(l) for l in lines[:j])))
                    display = line[:lchars]
                    if display:
                        _draw_bubble(draw, display, W // 2 - 150, y, 300, "left", (40, 40, 60, int(alpha * 0.85)), font)

        elif scene["type"] == "punchline":
            alpha = int(fade * 255)
            if alpha > 0:
                bc = alpha * 0.85
                text = scene["text"][:chars_visible]
                if text:
                    bbox = punch_font.getbbox(text)
                    tw = bbox[2] - bbox[0]
                    bx = (W - tw) // 2 - 40
                    by = H // 2 - 80
                    _draw_rounded_rect(draw, bx, by, bx + tw + 80, by + 160, 30, (60, 30, 30, int(bc)))
                    for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                        _center_text(draw, text, W // 2 + dx + random.randint(-2, 2), H // 2 + dy, punch_font, (255, 180, 30, alpha), shadow_alpha=40)
                    _center_text(draw, text, W // 2, H // 2, punch_font, (255, 220, 50, alpha), shadow=True, shadow_alpha=80)

    hook_dur = 1.2
    if t < hook_dur:
        alpha = int(min(1.0, t / 0.3, (hook_dur - t) / 0.3) * 255)
        if alpha > 0:
            hook_font = _get_font(120)
            theme_emoji = _theme_emoji(scenes[0].get("text", "") if scenes else "")
            hook_text = f"{theme_emoji}  \u0410\u041d\u0415\u041a\u0414\u041e\u0422"
            bbox = hook_font.getbbox(hook_text)
            tw = bbox[2] - bbox[0]
            bx = (W - tw) // 2 - 40
            by = H // 2 - 80
            _draw_rounded_rect(draw, bx, by, bx + tw + 80, by + 160, 40, (20, 20, 40, int(alpha * 0.9)))
            _center_text(draw, hook_text, W // 2, H // 2, hook_font, (255, 255, 200, alpha), shadow=True, shadow_alpha=80)

    outro_start = total_dur - 2.5
    if t > outro_start:
        frac = min(1.0, (t - outro_start) / 0.5)
        alpha = int(frac * 255)
        if alpha > 0:
            _center_text(draw, "\U0001f447 \u041f\u041e\u0414\u041f\u0418\u0428\u0418\u0421\u042c \U0001f447", W // 2, H // 3, _get_font(90), (255, 200, 50, alpha), shadow=True, shadow_alpha=80)
            _center_text(draw, "@Anetdodik", W // 2, H // 3 + 130, _get_font(60), (255, 255, 255, alpha), shadow=True, shadow_alpha=60)

    _draw_progress_bar(draw, t, total_dur)

    frame = Image.alpha_composite(frame, overlay)
    return frame.convert("RGB")


def _center_text(draw, text, x, y, font, fill, shadow=False, shadow_alpha=60):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    bx = x - tw // 2
    by = y - th // 2
    if shadow:
        r, g, b, a = fill if len(fill) == 4 else (*fill, 255)
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, -5), (0, 5)]:
            draw.text((bx + dx, by + dy), text, font=font, fill=(0, 0, 0, min(255, a * shadow_alpha // 100)))
    draw.text((bx, by), text, font=font, fill=fill)


# ── Public ────────────────────────────────────────────────

def render_short(joke_text: str, output_path: str, hf_token: str = "", cf_account_id: str = "", cf_api_token: str = "") -> bool:
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)
    frame_dir = SHORTS_DIR / "frames"
    audio_dir = SHORTS_DIR / "audio"
    frame_dir.mkdir(exist_ok=True)
    audio_dir.mkdir(exist_ok=True)

    scenes = _parse_scenes(joke_text)
    if not scenes:
        logger.error("No scenes parsed from joke")
        return False

    palette = random.choice(PALETTES)
    hf_bg = _generate_background(joke_text, cf_id=cf_account_id, cf_token=cf_api_token, hf_token=hf_token)

    _generate_tts(joke_text, audio_dir / "voice.mp3")

    voice_dur = 0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1",
             str(audio_dir / "voice.mp3")],
            capture_output=True, text=True, timeout=15,
        )
        voice_dur = float(result.stdout.strip())
    except Exception:
        voice_dur = max(8, len(joke_text) * 0.08)

    audio_dur = max(voice_dur, 12) + 3.0
    total_dur = max(12, min(55, audio_dur))
    total_frames = int(total_dur * FPS)

    music_path = audio_dir / "music.wav"
    if not _select_music(total_dur, music_path):
        try:
            _generate_beat(total_dur, audio_dir / "beat.wav")
        except Exception as e:
            logger.error("Beat generation failed: %s", e)

    seg_lens = [len(s["text"]) for s in scenes]
    total_chars = sum(seg_lens) or 1
    padding_sec = 0.4
    scene_times = []
    cur = hook_dur = 1.2
    for i, seg_len in enumerate(seg_lens):
        seg_dur = max(0.8, (seg_len / total_chars) * max(voice_dur - cur, 3))
        end = min(cur + seg_dur + padding_sec, total_dur - 3.0)
        scene_times.append((cur, end))
        cur = end + padding_sec * 0.3

    rng = random.Random()
    particles = [
        {
            "x": rng.randint(0, W), "y": rng.randint(0, H),
            "vx": rng.uniform(-10, 10), "vy": rng.uniform(-20, -5),
            "radius": rng.randint(2, 4),
            "freq": rng.uniform(0.5, 2.0),
            "phase": rng.random() * math.tau,
        }
        for _ in range(20)
    ]

    logger.info("Rendering %d frames (%.1fs), %d scenes, voice=%.1fs",
                total_frames, total_dur, len(scenes), voice_dur)

    for f_idx in range(total_frames):
        t = f_idx / FPS
        img = _render_frame(
            t, total_dur, scenes, scene_times,
            palette, particles, background=hf_bg,
        )
        img.save(frame_dir / f"f_{f_idx:06d}.png")

    voice_path = audio_dir / "voice.mp3"
    has_voice = voice_path.exists() and voice_path.stat().st_size > 100
    has_music = music_path.exists() and music_path.stat().st_size > 100
    has_beat = (audio_dir / "beat.wav").exists() and (audio_dir / "beat.wav").stat().st_size > 100

    inputs = ["-framerate", str(FPS), "-i", str(frame_dir / "f_%06d.png")]
    filter_chains = []
    output_maps = []

    if has_voice and has_music:
        inputs.extend(["-i", str(voice_path), "-i", str(music_path)])
        filter_chains = ["[1:a]volume=1.5[a_voice]", "[2:a]volume=0.2[a_music]", "[a_voice][a_music]amix=inputs=2:duration=first[aout]"]
        output_maps = ["-map", "0:v", "-map", "[aout]"]
    elif has_voice and has_beat:
        inputs.extend(["-i", str(voice_path), "-i", str(audio_dir / "beat.wav")])
        filter_chains = ["[1:a]volume=1.5[a_voice]", "[2:a]volume=0.25[a_beat]", "[a_voice][a_beat]amix=inputs=2:duration=first[aout]"]
        output_maps = ["-map", "0:v", "-map", "[aout]"]
    elif has_voice:
        inputs.extend(["-i", str(voice_path)])
        filter_chains = ["[1:a]volume=1.5[aout]"]
        output_maps = ["-map", "0:v", "-map", "[aout]"]
    else:
        inputs.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"])
        output_maps = []

    cmd = [
        "ffmpeg", "-y", *inputs,
        *(["-filter_complex", ";".join(filter_chains)] if filter_chains else []),
        *output_maps,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-preset", "fast",
        "-crf", "22",
        "-movflags", "+faststart",
        "-c:a", "aac",
        "-b:a", "128k",
        "-shortest",
        output_path,
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=600)
        logger.info("Rendered short: %s (%.1fs, %d frames)", output_path, total_dur, total_frames)
        return True
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else ""
        logger.error("FFmpeg failed: %s", stderr[:1500])
        return False
    except Exception as e:
        logger.exception("Failed to render short")
        return False
    finally:
        for d in [frame_dir, audio_dir]:
            if d.exists():
                shutil.rmtree(d)


def upload_short(
    video_path: str, title: str, description: str,
    refresh_token: str, client_id: str, client_secret: str,
    privacy_status: str = "private",
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
                "description": (
                    description + "\n\n\u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C: https://t.me/Anetdodik"
                ).strip()[:5000],
                "tags": ["\u0430\u043D\u0435\u043A\u0434\u043E\u0442", "\u044E\u043C\u043E\u0440", "shorts", "\u0441\u043C\u0435\u0448\u043D\u043E\u0435"],
            },
            "status": {
                "privacyStatus": privacy_status,
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
        logger.info("Uploaded short: https://youtu.be/%s (privacy: %s)", video_id, privacy_status)
        return video_id
    except Exception as e:
        logger.exception("Failed to upload short")
        return None
