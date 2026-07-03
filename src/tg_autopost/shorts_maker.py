import logging
import math
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
from .music_fetcher import ensure_music

logger = logging.getLogger(__name__)

SHORTS_DIR = Path("data/shorts")
MUSIC_DIR = Path("data/music")
SFX_DIR = Path("data/sfx")
W, H = 1080, 1920
FPS = 24

PALETTES = [
    [(0.63, 0.30, 0.10), (0.70, 0.40, 0.15)],
    [(0.70, 0.35, 0.08), (0.75, 0.45, 0.12)],
]

TEXT_ACCENT = (255, 210, 80)

CHARACTER_PATH = Path("data/anekdotik_character.png")
STAGE_BG_PATH = Path("data/stage_background.png")


def _hsl_rgb(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    path = FONT_PATH or "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(str(path), size)


# ── Scene parser ─────────────────────────────────────────

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


def _guess_theme_name(joke_text: str) -> str:
    text = joke_text.lower()
    topics = {
        "\u0432\u0440\u0430\u0447": "\u043F\u0440\u043E \u0432\u0440\u0430\u0447\u0435\u0439",
        "\u0440\u0430\u0431\u043E\u0442\u0430": "\u043F\u0440\u043E \u0440\u0430\u0431\u043E\u0442\u0443",
        "\u043C\u0443\u0436": "\u043F\u0440\u043E \u0441\u0435\u043C\u044C\u044E",
        "\u0430\u0440\u043C\u0438": "\u043F\u0440\u043E \u0430\u0440\u043C\u0438\u044E",
        "\u0432\u043E\u0434\u043A\u0430": "\u043F\u0440\u043E \u0432\u044B\u043F\u0438\u0432\u043A\u0443",
        "\u0448\u043A\u043E\u043B": "\u043F\u0440\u043E \u0448\u043A\u043E\u043B\u0443",
        "\u043A\u043E\u0442": "\u043F\u0440\u043E \u0436\u0438\u0432\u043E\u0442\u043D\u044B\u0445",
        "\u0434\u0435\u043D\u044C\u0433": "\u043F\u0440\u043E \u0434\u0435\u043D\u044C\u0433\u0438",
    }
    for kw, theme in topics.items():
        if kw in text:
            return theme
    return ""


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


# ── Background ───────────────────────────────────────────

TOPIC_PROMPTS: list[tuple[list[str], str]] = [
    (["\u0440\u0430\u0431\u043E\u0442\u0430", "\u043E\u0444\u0438\u0441", "\u0448\u0435\u0444"], "\u0440\u0430\u0431\u043E\u0442\u0430"),
    (["\u0432\u0440\u0430\u0447", "\u0431\u043E\u043B\u044C\u043D\u0438\u0446\u0430", "\u043F\u0430\u0446\u0438\u0435\u043D\u0442"], "\u0432\u0440\u0430\u0447"),
    (["\u043C\u0443\u0436", "\u0436\u0435\u043D", "\u0441\u0435\u043C\u044C", "\u0442\u0435\u0449", "\u0436\u0435\u043D\u0430"], "\u0441\u0435\u043C\u044C"),
    (["\u0430\u0440\u043C\u0438", "\u0432\u043E\u0435\u043D", "\u0441\u043E\u043B\u0434\u0430\u0442"], "\u0430\u0440\u043C\u0438"),
    (["\u0432\u043E\u0434\u043A\u0430", "\u043F\u0438\u0432\u043E", "\u0431\u0430\u0440", "\u043F\u044C\u044F\u043D"], "\u0432\u043E\u0434\u043A\u0430"),
    (["\u0448\u043A\u043E\u043B", "\u0443\u0447\u0438\u0442\u0435\u043B", "\u0443\u0440\u043E\u043A", "\u043A\u043B\u0430\u0441\u0441"], "\u0448\u043A\u043E\u043B"),
    (["\u043A\u043E\u0442", "\u043A\u043E\u0448\u043A", "\u0441\u043E\u0431\u0430\u043A", "\u0436\u0438\u0432\u043E\u0442\u043D"], "\u043A\u043E\u0442"),
    (["\u0434\u0435\u043D\u044C\u0433", "\u0431\u0430\u043D\u043A", "\u0431\u0438\u0437\u043D\u0435\u0441", "\u043C\u0438\u043B\u043B\u0438\u043E\u043D"], "\u0434\u0435\u043D\u044C\u0433"),
]

THEME_SCENES = {
    "\u0440\u0430\u0431\u043E\u0442\u0430": "modern office interior with desks, soft natural lighting, professional atmosphere",
    "\u0432\u0440\u0430\u0447": "clean hospital corridor, medical equipment, white walls, clinical lighting",
    "\u0441\u0435\u043C\u044C": "cozy home living room, warm lamp light, comfortable armchair, fireplace",
    "\u0430\u0440\u043C\u0438": "military barracks, camouflage nets, morning sunlight, army atmosphere",
    "\u0432\u043E\u0434\u043A\u0430": "russian pub interior, wooden tables, dim warm lighting, rustic atmosphere",
    "\u0448\u043A\u043E\u043B": "empty classroom, wooden desks, chalkboard, sunlight through window",
    "\u043A\u043E\u0442": "sunlit room with a sleeping cat on a windowsill, peaceful atmosphere",
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


# ── Audio ────────────────────────────────────────────────

async def _edge_tts(text: str, output_path: Path) -> float:
    try:
        import edge_tts
        communicate = edge_tts.Communicate(text, "ru-RU-DariyaNeural")
        await communicate.save(str(output_path))
        if output_path.stat().st_size > 100:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
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
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
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
    MUSIC_DIR.mkdir(parents=True, exist_ok=True)
    tracks = list(MUSIC_DIR.glob("*.mp3"))
    if not tracks:
        return False
    track = random.choice(tracks)
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(track)],
            capture_output=True, text=True, timeout=15,
        )
        track_dur = float(result.stdout.strip()) or 30
        loop_count = int(math.ceil(total_dur / max(track_dur, 1)))
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(loop_count),
            "-i", str(track),
            "-t", str(total_dur),
            "-af", "volume=0.15",
            "-acodec", "pcm_s16le",
            "-ar", "44100",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=30)
        logger.info("Selected music: %s (%.1fs, looped x%d)", track.name, track_dur, loop_count)
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
        samples[i] += pad_env * (0.5 * math.sin(2 * math.pi * pad_freq * t) + 0.3 * math.sin(2 * math.pi * pad_freq * 2 * t))
    peak = max(abs(s) for s in samples) or 1
    ints = [int(s / peak * 30000) for s in samples]
    with open(output_path, "wb") as f:
        data_size = len(ints) * 2
        f.write(b"RIFF"); f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE"); f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data"); f.write(struct.pack("<I", data_size))
        for s in ints:
            f.write(struct.pack("<h", s))
    logger.info("Generated beat: %.1fs", duration)


# ── SFX ──────────────────────────────────────────────────

SFX_TRACKS = {
    "hit": "https://github.com/NEVKrutov-tech/tgpost/raw/main/data/sfx/hit.wav" if False else None,
    "swoosh": None,
}

def _ensure_sfx() -> dict[str, Path]:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in ["hit", "swoosh", "laugh"]:
        p = SFX_DIR / f"{name}.wav"
        if p.exists() and p.stat().st_size > 1000:
            result[name] = p
    return result


# ── Frame rendering (viral Shorts style) ─────────────────

def _render_gradient_strip(palette, shift: float) -> Image.Image:
    h1, s1, l1 = palette[0]; h2, s2, l2 = palette[1]
    ch1 = (h1 + shift) % 1.0; ch2 = (h2 + shift) % 1.0
    c1 = _hsl_rgb(ch1, s1, l1); c2 = _hsl_rgb(ch2, s2, l2)
    img = Image.new("RGB", (1, H))
    pix = img.load()
    for y in range(H):
        f = y / H
        pix[0, y] = (int(c1[0] + (c2[0] - c1[0]) * f), int(c1[1] + (c2[1] - c1[1]) * f), int(c1[2] + (c2[2] - c1[2]) * f))
    return img


LINE_H = None
CHAR_IMG = None
CHAR_W = CHAR_H = 0
CHAR_ASPECT = 1.0
STAGE_BG = None

def _load_assets():
    global CHAR_IMG, CHAR_W, CHAR_H, CHAR_ASPECT, STAGE_BG, LINE_H
    if CHAR_IMG is not None:
        return
    if CHARACTER_PATH.exists():
        CHAR_IMG = Image.open(CHARACTER_PATH).convert("RGBA")
        CHAR_W, CHAR_H = CHAR_IMG.size
        CHAR_ASPECT = CHAR_W / CHAR_H
        # Scale character to fit on stage (~65% of frame height)
        target_h = int(H * 0.7)
        scale = target_h / CHAR_H
        new_w = int(CHAR_W * scale)
        CHAR_IMG = CHAR_IMG.resize((new_w, target_h), Image.Resampling.LANCZOS)
        CHAR_W, CHAR_H = new_w, target_h
        logger.info("Loaded character: %dx%d (aspect %.2f)", CHAR_W, CHAR_H, CHAR_ASPECT)
    else:
        logger.warning("Character image not found at %s", CHARACTER_PATH)

    if STAGE_BG_PATH.exists():
        STAGE_BG = Image.open(STAGE_BG_PATH).convert("RGB")
        STAGE_BG = STAGE_BG.resize((W, H), Image.Resampling.LANCZOS)
        logger.info("Loaded stage background")
    else:
        logger.warning("Stage background not found at %s", STAGE_BG_PATH)


def _render_speech_bubble(draw, text, word_idx, box_x, box_y, box_w, box_h):
    words = text.split()
    if not words:
        return

    padding = 30
    font = _get_font(64)
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + 12
    max_chars = max(1, (box_w - padding * 2) // (font.getbbox("A")[2] - font.getbbox("A")[0] + 4))

    lines = []
    cur_line = []
    for w in words:
        test = " ".join(cur_line + [w])
        if len(test) <= max_chars:
            cur_line.append(w)
        else:
            lines.append(cur_line)
            cur_line = [w]
    if cur_line:
        lines.append(cur_line)

    total_h = len(lines) * line_h
    start_y = box_y + (box_h - total_h) // 2

    _draw_rounded_rect(draw, box_x, box_y, box_x + box_w, box_y + box_h, 30, (0, 0, 0, 200))

    # Tail of speech bubble pointing down toward character
    tail_x = box_x + box_w // 2
    tail_y = box_y + box_h
    _draw_rounded_rect(draw, tail_x - 15, tail_y - 5, tail_x + 15, tail_y + 25, 5, (0, 0, 0, 200))

    word_counter = 0
    for li, line_words in enumerate(lines):
        x = box_x + padding
        y = start_y + li * line_h
        for w in line_words:
            is_curr = word_counter == word_idx
            c = TEXT_ACCENT if is_curr else (255, 255, 255, 255)
            f = _get_font(70) if is_curr else font
            draw.text((x, y), w + " ", font=f, fill=c)
            x += f.getbbox(w + " ")[2] - f.getbbox(w + " ")[0]
            word_counter += 1


def _draw_rounded_rect(draw, x1, y1, x2, y2, radius, fill):
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill)


def _center_text(draw, text, x, y, font, fill, shadow=False, shadow_alpha=60):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    bx = x - tw // 2; by = y - th // 2
    if shadow:
        r, g, b, a = fill if len(fill) == 4 else (*fill, 255)
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, -5), (0, 5)]:
            draw.text((bx + dx, by + dy), text, font=font, fill=(0, 0, 0, min(255, a * shadow_alpha // 100)))
    draw.text((bx, by), text, font=font, fill=fill)


def _draw_subtitle_text(draw, text: str, current_word_idx: int, font, box_x, box_y, box_w, box_h, accent_color):
    words = text.split()
    padding = 30
    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + 10
    max_chars_per_line = max(1, (box_w - padding * 2) // (font.getbbox("A")[2] - font.getbbox("A")[0] + 4))

    lines = []
    current_line = []
    for w in words:
        test = " ".join(current_line + [w])
        if len(test) <= max_chars_per_line:
            current_line.append(w)
        else:
            lines.append(current_line)
            current_line = [w]
    if current_line:
        lines.append(current_line)

    total_h = len(lines) * line_h
    start_y = box_y + (box_h - total_h) // 2
    word_counter = 0

    for li, line_words in enumerate(lines):
        x = box_x + padding
        y = start_y + li * line_h
        for w in line_words:
            is_current = (word_counter == current_word_idx)
            if is_current:
                c = accent_color
                f = _get_font(62)
            else:
                c = (255, 255, 255, 255)
                f = font
            draw.text((x, y), w + " ", font=f, fill=c)
            x += f.getbbox(w + " ")[2] - f.getbbox(w + " ")[0]
            word_counter += 1



def _get_word_index(text: str, local_t: float, ttl_dur: float) -> int:
    words = text.split()
    if not words:
        return 0
    speed = len(words) / max(ttl_dur, 0.5)
    return min(len(words) - 1, int(speed * local_t))


def _render_frame(t: float, total_dur: float,
                  scenes: list[dict], scene_times: list[tuple[float, float]],
                  palette: list,
                  sfx_hit_t: float | None = None,
                  background: Image.Image | None = None) -> Image.Image:
    if STAGE_BG is not None:
        frame = STAGE_BG.copy().convert("RGBA")
    elif background is not None:
        frame = background.resize((W, H)).convert("RGBA")
    else:
        strip = _render_gradient_strip(palette, t * 0.01)
        frame = strip.resize((W, H)).convert("RGBA")

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Dark vignette overlay for atmosphere
    _draw_rounded_rect(draw, 0, 0, W, H, 0, (0, 0, 0, 60))

    # --- Scene text timing ---
    visible = [(i, st, et) for i, (st, et) in enumerate(scene_times) if st <= t <= et]

    # --- Title card ---
    if t < 1.2:
        a = int(min(1.0, t / 0.4, (1.2 - t) / 0.3) * 255)
        if a > 0:
            emoji = _theme_emoji(scenes[0]["text"] if scenes else "")
            scale = 0.4 + 0.6 * min(1.0, t / 0.5)
            sf = _get_font(int(120 * scale))
            if sf.size > 30:
                _center_text(draw, f"{emoji} \u0410\u041D\u0415\u041A\u0414\u041E\u0422", W // 2, H // 2 - 40, sf, (255, 240, 180, a))
        return Image.alpha_composite(frame, overlay).convert("RGB")

    # --- Outro ---
    outro_start = total_dur - 2.5
    if t > outro_start:
        frac = min(1.0, (t - outro_start) / 0.4)
        a = int(frac * 255)
        if a > 0:
            _center_text(draw, "\U0001f447 \u041F\u041E\u0414\u041F\u0418\u0428\u0418\u0421\u042c", W // 2, H // 3, _get_font(80), (255, 210, 80, a))
            _center_text(draw, "@Anetdodik", W // 2, H // 3 + 120, _get_font(56), (255, 255, 255, a))
        return Image.alpha_composite(frame, overlay).convert("RGB")

    # --- Character rendering ---
    char_x = (W - CHAR_W) // 2
    char_y = H - CHAR_H + 60  # bottom of frame, slightly raised

    if CHAR_IMG is not None:
        # Animation: idle bob + talk pulse
        bob = math.sin(t * 2.5) * 3  # ±3px idle bob
        talk = math.sin(t * 6.0) * 2.0

        # Find current scene for punchline effects
        is_punch_scene = False
        local_t_in_scene = 0
        if visible:
            vi, st, et = visible[0]
            sce = scenes[vi]
            is_punch_scene = sce["type"] == "punchline"
            local_t_in_scene = t - st

        # Punchline: bigger bounce + scale
        punch_scale = 1.0
        punch_bounce = 0
        if is_punch_scene and local_t_in_scene < 0.5:
            punch_progress = min(1.0, local_t_in_scene / 0.5)
            punch_scale = 1.0 + 0.08 * math.sin(punch_progress * math.pi)
            punch_bounce = -15 * math.sin(punch_progress * math.pi)

        char_frame = CHAR_IMG

        # Apply punchline scale
        if punch_scale != 1.0:
            nw = int(CHAR_W * punch_scale)
            nh = int(CHAR_H * punch_scale)
            char_frame = char_frame.resize((nw, nh), Image.Resampling.LANCZOS)

        cf_w, cf_h = char_frame.size
        final_x = (W - cf_w) // 2
        final_y = char_y + int(bob + talk + punch_bounce)

        # Spotlight glow behind character
        glow_h = int(cf_h * 0.4)
        glow_y = final_y + cf_h // 4
        for i in range(glow_h):
            a = int(80 * (1 - i / glow_h) * (0.8 + 0.2 * math.sin(t * 0.5)))
            _draw_rounded_rect(draw, W // 2 - cf_w // 3, glow_y + i, W // 2 + cf_w // 3, glow_y + i + 1, 0, (255, 220, 150, a))

        # Paste character onto frame at correct position
        frame.paste(char_frame, (final_x, final_y), char_frame)

        # Blinking overlay on the overlay layer
        blink_cycle = 2.5
        blink_dur = 0.1
        blink_phase = (t % blink_cycle)
        if blink_phase < blink_dur:
            blink_alpha = int(min(1.0, blink_phase / 0.03, (blink_dur - blink_phase) / 0.03) * 120)
            # Eye position: roughly center of character, upper portion
            eye_x = final_x + cf_w // 2 - 30
            eye_y = final_y + cf_h // 4 - 5
            _draw_rounded_rect(draw, eye_x, eye_y, eye_x + 60, eye_y + 15, 0, (0, 0, 0, blink_alpha))

    # --- Speech bubble ---
    if visible:
        vi, st, et = visible[0]
        scene = scenes[vi]
        local_t = max(0, t - st)
        ttl_dur = max(0.5, et - st)
        fade = min(1.0, local_t / 0.15)
        alpha = min(255, int(fade * 255))

        if scene["type"] in ("dialogue", "punchline", "narrative") and alpha > 0:
            word_idx = _get_word_index(scene["text"], local_t, ttl_dur)

            # Speech bubble above character
            bubble_w = min(W - 160, 880)
            bubble_h = 200
            bubble_x = (W - bubble_w) // 2
            bubble_y = H - CHAR_H - bubble_h - 20  # above character

            _render_speech_bubble(draw, scene["text"], word_idx, bubble_x, bubble_y, bubble_w, bubble_h)

            # Punchline flash
            if scene["type"] == "punchline" and 0.05 < local_t < 0.35:
                fa = int((1 - abs(local_t - 0.2) / 0.15) * 40)
                if fa > 0:
                    _draw_rounded_rect(draw, 0, 0, W, H, 0, (255, 255, 255, fa))

    # --- Progress bar ---
    bar_h = 4
    bar_y = H - bar_h - 20
    bar_w = W - 120
    bar_x = 60
    progress = min(1.0, t / max(total_dur, 1))
    _draw_rounded_rect(draw, bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, 2, (255, 255, 255, 30))
    fw = int(bar_w * progress)
    if fw > 0:
        _draw_rounded_rect(draw, bar_x, bar_y, bar_x + fw, bar_y + bar_h, 2, (255, 215, 0, 180))

    frame = Image.alpha_composite(frame, overlay)
    return frame.convert("RGB")


# ── Public ────────────────────────────────────────────────

def render_short(joke_text: str, output_path: str, hf_token: str = "", cf_account_id: str = "", cf_api_token: str = "") -> bool:
    _load_assets()
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)
    ensure_music()
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
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_dir / "voice.mp3")],
            capture_output=True, text=True, timeout=15,
        )
        voice_dur = float(result.stdout.strip())
    except Exception:
        voice_dur = max(8, len(joke_text) * 0.08)

    audio_dur = max(voice_dur, 12) + 2.5
    total_dur = max(12, min(55, audio_dur))
    total_frames = int(total_dur * FPS)

    music_path = audio_dir / "music.wav"
    if not _select_music(total_dur, music_path):
        try:
            _generate_beat(total_dur, audio_dir / "beat.wav")
        except Exception as e:
            logger.error("Beat generation failed: %s", e)

    punchline_idx = max(i for i, s in enumerate(scenes) if s["type"] == "punchline") if any(s["type"] == "punchline" for s in scenes) else len(scenes) - 1

    # Reserve time for punchline (2.5s) + outro (3.0s = total_dur - end_cap)
    end_cap = total_dur - 3.0
    available = end_cap - 1.2  # time after title card
    punch_min = 2.0
    punch_max = min(6.0, available * 0.35)
    punch_dur = max(punch_min, min(punch_max, len(scenes[punchline_idx]["text"]) / max(voice_dur, 5) * available))

    # Allocate remaining time to non-punch scenes proportionally
    non_punch_total = sum(len(s["text"]) for i, s in enumerate(scenes) if i != punchline_idx) or 1
    non_punch_avail = available - punch_dur

    cur = 1.2
    scene_times = []
    last_non_punch_end = 1.2
    for i, s in enumerate(scenes):
        seg_len = len(s["text"])
        if i == punchline_idx:
            start = max(cur, last_non_punch_end)
            end = min(start + punch_dur + 0.5, end_cap)
            scene_times.append((start, end))
        else:
            seg_dur = max(1.0, (seg_len / non_punch_total) * non_punch_avail + 0.3)
            end = min(cur + seg_dur, end_cap - punch_dur - 0.5)
            if end > cur:
                scene_times.append((cur, end))
                cur = end + 0.1
                last_non_punch_end = end
            else:
                scene_times.append((cur, cur + 0.5))
                last_non_punch_end = cur + 0.5

    # If punchline still has zero duration, give it time
    pi_st, pi_en = scene_times[punchline_idx]
    if pi_en <= pi_st:
        scene_times[punchline_idx] = (cur, min(cur + punch_dur, end_cap))

    hit_time = scene_times[punchline_idx][0] + 0.1 if punchline_idx < len(scene_times) else None

    logger.info("Rendering %d frames (%.1fs), %d scenes, voice=%.1fs", total_frames, total_dur, len(scenes), voice_dur)

    for f_idx in range(total_frames):
        t = f_idx / FPS
        img = _render_frame(t, total_dur, scenes, scene_times, palette, sfx_hit_t=hit_time, background=hf_bg)
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
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "22",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", output_path,
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
            token=None, refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id, client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/youtube.upload"],
        )
        youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
        body = {
            "snippet": {
                "title": title[:100],
                "description": (description + "\n\n\u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C: https://t.me/Anetdodik").strip()[:5000],
                "tags": ["\u0430\u043D\u0435\u043A\u0434\u043E\u0442", "\u044E\u043C\u043E\u0440", "shorts", "\u0441\u043C\u0435\u0448\u043D\u043E\u0435"],
            },
            "status": {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False},
        }
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        response = request.execute()
        video_id = response["id"]
        logger.info("Uploaded short: https://youtu.be/%s (privacy: %s)", video_id, privacy_status)
        return video_id
    except Exception as e:
        logger.exception("Failed to upload short")
        return None
