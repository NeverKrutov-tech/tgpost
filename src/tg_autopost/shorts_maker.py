import logging
import math
import random
import struct
import subprocess
import json
import time

import shutil
import asyncio
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

MAX_WORDS_PER_FRAME = 6
FRAME_DUR = 2.5

TEXT_ACCENT = (255, 210, 80)
TEXT_MAIN = (255, 255, 255)
BG_DIM = 80


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

TOPIC_THEMES: list[tuple[list[str], str]] = [
    (["\u0440\u0430\u0431\u043E\u0442\u0430", "\u043E\u0444\u0438\u0441", "\u0448\u0435\u0444"], "office"),
    (["\u0432\u0440\u0430\u0447", "\u0431\u043E\u043B\u044C\u043D\u0438\u0446\u0430", "\u043F\u0430\u0446\u0438\u0435\u043D\u0442"], "hospital"),
    (["\u043C\u0443\u0436", "\u0436\u0435\u043D", "\u0441\u0435\u043C\u044C", "\u0442\u0435\u0449", "\u0436\u0435\u043D\u0430"], "family"),
    (["\u0430\u0440\u043C\u0438", "\u0432\u043E\u0435\u043D", "\u0441\u043E\u043B\u0434\u0430\u0442"], "army"),
    (["\u0432\u043E\u0434\u043A\u0430", "\u043F\u0438\u0432\u043E", "\u0431\u0430\u0440", "\u043F\u044C\u044F\u043D"], "pub"),
    (["\u0448\u043A\u043E\u043B", "\u0443\u0447\u0438\u0442\u0435\u043B", "\u0443\u0440\u043E\u043A", "\u043A\u043B\u0430\u0441\u0441"], "school"),
    (["\u043A\u043E\u0442", "\u043A\u043E\u0448\u043A", "\u0441\u043E\u0431\u0430\u043A", "\u0436\u0438\u0432\u043E\u0442\u043D"], "animal"),
    (["\u0434\u0435\u043D\u044C\u0433", "\u0431\u0430\u043D\u043E\u043A", "\u0431\u0438\u0437\u043D\u0435\u0441", "\u043C\u0438\u043B\u043B\u0438\u043E\u043D"], "money"),
]

SMOOTH_ROUGH = [("\u0448\u0435\u0440\u0448\u0430\u0432", "rough"), ("\u0433\u043B\u0430\u0434\u043A", "smooth")]

BG_DIR = Path("data/backgrounds")


def _load_background(joke_text: str) -> Image.Image:
    text = joke_text.lower()
    theme = "default"
    for words, theme_key in TOPIC_THEMES:
        for w in words:
            if w in text:
                theme = theme_key
                break
    bg_path = BG_DIR / f"{theme}.png"
    if bg_path.exists():
        try:
            return Image.open(bg_path).convert("RGBA")
        except Exception:
            pass
    return Image.new("RGBA", (W, H), (20, 15, 30))


# ── Audio ────────────────────────────────────────────────

_SILERO_MODEL = None
_SILERO_SR = 48000

def _silero_tts(text: str, output_path: Path) -> float:
    global _SILERO_MODEL
    try:
        if _SILERO_MODEL is None:
            import os
            os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
            import torch
            logger.info("Loading Silero TTS model...")
            model, _ = torch.hub.load(
                repo_or_dir='snakers4/silero-models',
                model='silero_tts',
                language='ru',
                speaker='v4_ru',
                trust_repo=True,
            )
            model.to('cpu')
            _SILERO_MODEL = model
            logger.info("Silero model loaded")
        import soundfile as sf
        audio = _SILERO_MODEL.apply_tts(text=text, speaker='baya', sample_rate=_SILERO_SR)
        sf.write(str(output_path), audio, _SILERO_SR)
        if output_path.stat().st_size > 100:
            result = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(output_path)],
                capture_output=True, text=True, timeout=15,
            )
            dur = float(result.stdout.strip())
            logger.info("Generated TTS via Silero: %.1fs", dur)
            return dur
    except Exception as e:
        logger.warning("Silero TTS failed: %s", e)
    return 0.0


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
    dur = _silero_tts(text, output_path)
    if dur > 0:
        return dur
    dur = asyncio.run(_edge_tts(text, output_path))
    if dur > 0:
        logger.info("Generated TTS via edge-tts: %.1fs", dur)
        return dur
    logger.info("Falling back to gTTS")
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

def _ensure_sfx() -> dict[str, Path]:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in ["laugh", "applause", "hit", "swoosh"]:
        p = SFX_DIR / f"{name}.wav"
        if p.exists() and p.stat().st_size > 1000:
            result[name] = p
    return result


# ── Frame rendering ──────────────────────────────────────

def _split_into_frames(scenes: list[dict]) -> list[dict]:
    frames = []
    for si, scene in enumerate(scenes):
        words = scene["text"].split()
        chunks = []
        for i in range(0, len(words), MAX_WORDS_PER_FRAME):
            chunk = " ".join(words[i:i + MAX_WORDS_PER_FRAME])
            is_punch = scene["type"] == "punchline"
            is_last = (i + MAX_WORDS_PER_FRAME >= len(words))
            chunks.append({
                "text": chunk,
                "scene_type": scene["type"],
                "is_last_chunk": is_last,
                "word_offset": i,
                "scene_idx": si,
            })
            if is_punch and is_last:
                break
        frames.extend(chunks)
    return frames


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


def _get_word_index(text: str, local_t: float, ttl_dur: float) -> int:
    words = text.split()
    if not words:
        return 0
    speed = len(words) / max(ttl_dur, 0.5)
    return min(len(words) - 1, int(speed * local_t))


def _render_text_center(draw, text: str, word_idx: int, y_center: int, frame_w: int, font_size: int, is_punchline: bool):
    words = text.split()
    if not words:
        return

    font = _get_font(font_size)
    small_font = _get_font(font_size - 4)
    spacing = 8

    line_w = frame_w - 120
    lines = []
    cur = []
    for w in words:
        test = " ".join(cur + [w])
        tw, _ = draw.textbbox((0, 0), test, font=font)[2:4]
        if tw <= line_w or not cur:
            cur.append(w)
        else:
            lines.append(cur)
            cur = [w]
    if cur:
        lines.append(cur)

    line_h = font.getbbox("Ag")[3] - font.getbbox("Ag")[1] + spacing
    total_h = len(lines) * line_h
    start_y = y_center - total_h // 2

    word_counter = 0
    for li, line_words in enumerate(lines):
        line_text = " ".join(line_words)
        tw, _ = draw.textbbox((0, 0), line_text, font=font)[2:4]
        x_start = (frame_w - tw) // 2
        y = start_y + li * line_h
        cx = x_start
        for w in line_words:
            is_curr = (word_counter == word_idx)
            f = font if is_curr else small_font
            c = TEXT_ACCENT if is_curr else TEXT_MAIN
            if is_curr:
                _center_text(draw, w, cx + f.getbbox(w + " ")[2] // 2, y, f, c, shadow=True, shadow_alpha=80)
            else:
                draw.text((cx, y), w + " ", font=f, fill=c)
            cx += f.getbbox(w + " ")[2] - f.getbbox(w + " ")[0]
            word_counter += 1


def _apply_ken_burns(bg: Image.Image, t: float, total_dur: float) -> Image.Image:
    content_dur = total_dur - 3.0
    if content_dur <= 0:
        return bg.resize((W, H), Image.Resampling.LANCZOS)
    progress = min(1.0, max(0.0, (t - 1.0) / content_dur))
    zoom = 1.0 + 0.06 * progress
    pan_x = int(40 * math.sin(progress * math.pi * 0.5))
    pan_y = int(80 * progress)
    cw, ch = bg.size
    new_w = int(cw * zoom)
    new_h = int(ch * zoom)
    resized = bg.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = max(0, min(new_w - W, (new_w - W) // 2 + pan_x))
    y = max(0, min(new_h - H, pan_y))
    return resized.crop((x, y, x + W, y + H))


def _render_frame(t: float, total_dur: float,
                  frames: list[dict], frame_times: list[tuple[float, float]],
                  bg_img: Image.Image | None = None,
                  text_only: bool = False) -> Image.Image:
    if text_only:
        frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    elif bg_img is not None:
        frame = _apply_ken_burns(bg_img, t, total_dur)
    else:
        frame = Image.new("RGBA", (W, H), (20, 15, 30))

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    visible = [(i, st, et) for i, (st, et) in enumerate(frame_times) if st <= t <= et]

    # --- Title card ---
    if t < 1.0:
        a = int(min(1.0, t / 0.3, (1.0 - t) / 0.3) * 255)
        if a > 0:
            _center_text(draw, "\U0001f4ac \u0410\u041D\u0415\u041A\u0414\u041E\u0422", W // 2, H // 2 - 40,
                         _get_font(110), (255, 240, 180, a), shadow=True)
        return Image.alpha_composite(frame, overlay).convert("RGB")

    # --- Outro ---
    outro_start = total_dur - 2.0
    if t > outro_start:
        frac = min(1.0, (t - outro_start) / 0.3)
        a = int(frac * 255)
        if a > 0:
            _center_text(draw, "\U0001f447 \u041F\u041E\u0414\u041F\u0418\u0428\u0418\u0421\u042c", W // 2, H // 2 - 80,
                         _get_font(80), (255, 210, 80, a), shadow=True)
            _center_text(draw, "t.me/Anetdodik", W // 2, H // 2 + 40,
                         _get_font(56), (255, 255, 255, a), shadow=True)
        return Image.alpha_composite(frame, overlay).convert("RGB")

    # --- Dark overlay for readability ---
    _draw_rounded_rect(draw, 0, 0, W, H, 0, (0, 0, 0, BG_DIM))

    if visible:
        fi, st, et = visible[0]
        frm = frames[fi]
        local_t = max(0, t - st)
        ttl_dur = max(0.5, et - st)

        word_idx = _get_word_index(frm["text"], local_t, ttl_dur)
        is_punch = frm["scene_type"] == "punchline"

        font_size = 80 if is_punch else 72
        y_center = H // 2 - 60

        _render_text_center(draw, frm["text"], word_idx, y_center, W, font_size, is_punch)

        if is_punch and frm["is_last_chunk"] and local_t < 0.4:
            fa = int((1 - local_t / 0.4) * 50)
            if fa > 0:
                _draw_rounded_rect(draw, 0, 0, W, H, 0, (255, 255, 255, fa))

    # --- Progress bar ---
    bar_h = 3
    bar_y = H - bar_h - 15
    bar_w = W - 100
    bar_x = 50
    progress = min(1.0, t / max(total_dur, 1))
    _draw_rounded_rect(draw, bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, 2, (255, 255, 255, 25))
    fw = int(bar_w * progress)
    if fw > 0:
        _draw_rounded_rect(draw, bar_x, bar_y, bar_x + fw, bar_y + bar_h, 2, (255, 215, 0, 160))

    if text_only:
        return frame
    frame = Image.alpha_composite(frame, overlay)
    return frame.convert("RGB")


# ── Public ────────────────────────────────────────────────

def _detect_aspect(joke_text: str) -> str:
    """Always return 9:16 for vertical Shorts."""
    return "9:16"


def _generate_veo_clip(prompt: str, api_key: str, output_path: str) -> bool:
    """Generate an 8s clip via Kie.ai Veo 3 Fast API. Returns True on success."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "prompt": prompt,
        "model": "veo3_fast",
        "aspect_ratio": "9:16",
        "duration": 8,
        "resolution": "720p",
    }
    try:
        r = requests.post("https://api.kie.ai/api/v1/veo/generate", json=payload, headers=headers, timeout=30)
        data = r.json()
        if data.get("code") != 200:
            logger.warning("Veo API submit failed: %s", data.get("msg", ""))
            return False
        task_id = data["data"]["taskId"]
        logger.info("Veo task submitted: %s", task_id)
        for _ in range(60):
            time.sleep(10)
            r2 = requests.get(f"https://api.kie.ai/api/v1/veo/record-info?taskId={task_id}", headers=headers, timeout=15)
            info = r2.json()
            flag = info.get("data", {}).get("successFlag")
            if flag == 1:
                urls = info["data"]["response"]["resultUrls"]
                vid = requests.get(urls[0], timeout=120)
                Path(output_path).write_bytes(vid.content)
                logger.info("Veo clip downloaded: %s (%d MB)", output_path, len(vid.content) // 1024 // 1024)
                return True
            if flag in (2, 3):
                logger.warning("Veo generation failed: %s", info.get("msg", ""))
                return False
        logger.warning("Veo generation timed out")
        return False
    except Exception as e:
        logger.warning("Veo API error: %s", e)
        return False


def _loop_video(input_path: str, output_path: str, target_dur: float) -> bool:
    """Loop an 8s clip to fill target_dur using FFmpeg concat."""
    try:
        loop_count = int(math.ceil(target_dur / 8.0))
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", str(loop_count),
            "-i", input_path,
            "-t", str(target_dur),
            "-c", "copy",
            output_path,
        ]
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        logger.info("Looped video: %s (%.1fs, x%d)", output_path, target_dur, loop_count)
        return True
    except Exception as e:
        logger.warning("Video loop failed: %s", e)
        return False


def _guess_veo_prompt(joke_text: str) -> str:
    """Build a cinematic prompt from joke text for Veo."""
    text = joke_text.lower()
    if any(w in text for w in ["\u0432\u0440\u0430\u0447", "\u0431\u043E\u043B\u044C\u043D\u0438\u0446\u0430"]):
        base = "clean hospital corridor, white walls, medical equipment, sterile clinical atmosphere"
    elif any(w in text for w in ["\u0440\u0430\u0431\u043E\u0442\u0430", "\u043E\u0444\u0438\u0441", "\u0448\u0435\u0444"]):
        base = "modern open-plan office, desks with monitors, large windows, natural daylight"
    elif any(w in text for w in ["\u043C\u0443\u0436", "\u0436\u0435\u043D", "\u0441\u0435\u043C\u044C", "\u0442\u0435\u0449"]):
        base = "cozy living room, warm lamp light, fireplace, comfortable armchairs"
    elif any(w in text for w in ["\u0430\u0440\u043C\u0438", "\u0432\u043E\u0435\u043D", "\u0441\u043E\u043B\u0434\u0430\u0442"]):
        base = "military barracks interior, metal bunk beds, morning sunlight through dusty windows"
    elif any(w in text for w in ["\u0432\u043E\u0434\u043A\u0430", "\u043F\u0438\u0432\u043E", "\u0431\u0430\u0440"]):
        base = "traditional pub interior, dark wooden tables, warm candlelight, brick walls"
    elif any(w in text for w in ["\u0448\u043A\u043E\u043B", "\u0443\u0447\u0438\u0442\u0435\u043B", "\u0443\u0440\u043E\u043A"]):
        base = "empty classroom, wooden desks, green chalkboard, sunlight streaming through windows"
    elif any(w in text for w in ["\u043A\u043E\u0442", "\u043A\u043E\u0448\u043A", "\u0441\u043E\u0431\u0430\u043A"]):
        base = "sunlit bedroom, cat sleeping on windowsill, cozy atmosphere"
    elif any(w in text for w in ["\u0434\u0435\u043D\u044C\u0433", "\u0431\u0430\u043D\u043A", "\u0431\u0438\u0437\u043D\u0435\u0441"]):
        base = "luxury corner office, floor-to-ceiling windows, panoramic city view, sleek furniture"
    else:
        base = "cozy interior room, warm ambient lighting, comfortable furniture"
    return f"{base}, cinematic vertical 9:16 video, photorealistic, slow camera movement, professional lighting, highly detailed, 8k"

def render_short(joke_text: str, output_path: str, **kwargs) -> bool:
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)
    ensure_music()
    frame_dir = SHORTS_DIR / "frames"
    audio_dir = SHORTS_DIR / "audio"
    frame_dir.mkdir(exist_ok=True)
    audio_dir.mkdir(exist_ok=True)

    bg = _load_background(joke_text)

    scenes = _parse_scenes(joke_text)
    if not scenes:
        logger.error("No scenes parsed from joke")
        return False

    video_frames = _split_into_frames(scenes)
    num_vf = len(video_frames)

    # ── Per-scene TTS for perfect sync ──
    scene_audio_dir = audio_dir / "scenes"
    scene_audio_dir.mkdir(exist_ok=True)
    scene_durs = []
    concat_list = []
    for i, scene in enumerate(scenes):
        scene_path = scene_audio_dir / f"s_{i:03d}.mp3"
        _generate_tts(scene["text"], scene_path)
        dur = 0.0
        try:
            r = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(scene_path)],
                capture_output=True, text=True, timeout=15,
            )
            dur = float(r.stdout.strip()) if r.stdout.strip() else 2.0
        except Exception:
            dur = max(1.0, len(scene["text"]) * 0.08)
        scene_durs.append(dur)
        concat_list.append(str(scene_path))
        logger.debug("Scene %d: '%s' -> %.1fs", i, scene["text"][:40], dur)

    voice_dur = sum(scene_durs)
    total_dur = 1.0 + voice_dur + 2.0
    total_dur = max(8, min(55, total_dur))
    total_frames = int(total_dur * FPS)

    # Concatenate all scene audio into one voice track
    concat_paths = "|".join(str(p) for p in concat_list)
    voice_path = audio_dir / "voice.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", f"concat:{concat_paths}", "-acodec", "copy", str(voice_path)],
        check=True, capture_output=True, timeout=30,
    )

    music_path = audio_dir / "music.wav"
    if not _select_music(total_dur, music_path):
        try:
            _generate_beat(total_dur, audio_dir / "beat.wav")
        except Exception as e:
            logger.error("Beat generation failed: %s", e)

    # Frame timing from per-scene durations
    frame_times = []
    punch_idx = next((i for i, vf in enumerate(video_frames) if vf["is_last_chunk"] and vf["scene_type"] == "punchline"), None)
    cur = 1.0
    for i, vf in enumerate(video_frames):
        dur = scene_durs[vf["scene_idx"]]
        if i == punch_idx:
            dur += 0.5
        dur = max(0.5, dur)
        frame_times.append((cur, cur + dur))
        cur += dur

    voice_path = audio_dir / "voice.mp3"
    has_voice = voice_path.exists() and voice_path.stat().st_size > 100
    has_music = music_path.exists() and music_path.stat().st_size > 100
    has_beat = (audio_dir / "beat.wav").exists() and (audio_dir / "beat.wav").stat().st_size > 100

    sfx_names = _ensure_sfx()
    has_sfx = len(sfx_names) > 0

    # Try Veo background first
    kie_api_key = kwargs.get("kie_api_key", "") or ""
    veo_bg = audio_dir / "bg_loop.mp4"
    use_veo = bool(kie_api_key) and _generate_veo_clip(_guess_veo_prompt(joke_text), kie_api_key, str(audio_dir / "background.mp4")) and _loop_video(str(audio_dir / "background.mp4"), str(veo_bg), total_dur)

    if use_veo:
        logger.info("Using Veo 3 background video")

    # Frame timing from per-scene durations
    frame_times = []
    punch_idx = next((i for i, vf in enumerate(video_frames) if vf["is_last_chunk"] and vf["scene_type"] == "punchline"), None)
    cur = 1.0
    for i, vf in enumerate(video_frames):
        dur = scene_durs[vf["scene_idx"]]
        if i == punch_idx:
            dur += 0.5
        dur = max(0.5, dur)
        frame_times.append((cur, cur + dur))
        cur += dur

    logger.info("Rendering %d frames (%.1fs), %d text frames, voice=%.1fs",
                total_frames, total_dur, num_vf, voice_dur)

    # Render frames (text-only overlays if using Veo, else full frames)
    render_text_only = use_veo
    for f_idx in range(total_frames):
        t = f_idx / FPS
        img = _render_frame(t, total_dur, video_frames, frame_times, bg_img=bg, text_only=render_text_only)
        if render_text_only:
            img.save(frame_dir / f"f_{f_idx:06d}.png")  # RGBA with transparent bg
        else:
            img.save(frame_dir / f"f_{f_idx:06d}.png")

    inputs = []
    input_count = 0
    filter_chains = []
    output_maps = []
    audio_filters = []

    if use_veo:
        inputs.extend(["-i", str(veo_bg)])
        input_count += 1
        # Overlay text frames
        inputs.extend(["-framerate", str(FPS), "-i", str(frame_dir / "f_%06d.png")])
        filter_chains.append(f"[0:v][1:v]overlay=0:0[vout]")
        output_maps = ["-map", "[vout]"]
    else:
        inputs = ["-framerate", str(FPS), "-i", str(frame_dir / "f_%06d.png")]
        input_count = 1
        output_maps = ["-map", "0:v"]

    if has_voice:
        inputs.extend(["-i", str(voice_path)])
        filter_chains.append(f"[{input_count}:a]volume=1.5,apad=whole_dur={total_dur + 2}[a_voice]")
        audio_filters.append("[a_voice]")
        input_count += 1
    if has_music:
        inputs.extend(["-i", str(music_path)])
        filter_chains.append(f"[{input_count}:a]volume=0.2[a_music]")
        audio_filters.append("[a_music]")
        input_count += 1
    elif has_beat:
        inputs.extend(["-i", str(audio_dir / "beat.wav")])
        filter_chains.append(f"[{input_count}:a]volume=0.25[a_beat]")
        audio_filters.append("[a_beat]")
        input_count += 1

    if has_sfx and "laugh" in sfx_names:
        inputs.extend(["-i", str(sfx_names["laugh"])])
        punchline_start = frame_times[-1][0] if frame_times else 0
        filter_chains.append(f"[{input_count}:a]adelay={int(punchline_start * 1000)}|{int(punchline_start * 1000)},volume=0.6[a_laugh]")
        audio_filters.append("[a_laugh]")
        input_count += 1

    if has_sfx and "applause" in sfx_names:
        inputs.extend(["-i", str(sfx_names["applause"])])
        outro_time = total_dur - 2.5
        filter_chains.append(f"[{input_count}:a]adelay={int(outro_time * 1000)}|{int(outro_time * 1000)},volume=0.5[a_applause]")
        audio_filters.append("[a_applause]")
        input_count += 1

    if audio_filters:
        mix_input = "".join(audio_filters)
        filter_chains.append(f"{mix_input}amix=inputs={len(audio_filters)}:duration=first[aout]")
        output_maps.extend(["-map", "[aout]"])
    else:
        inputs.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono"])
        if not use_veo:
            output_maps = []

    cmd = [
        "ffmpeg", "-y", *inputs,
        *(["-filter_complex", ";".join(filter_chains)] if filter_chains else []),
        *output_maps,
        "-vf", "eq=contrast=1.15:brightness=0.02:saturation=0.9,noise=alls=3:allf=t+u",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-preset", "fast", "-crf", "22",
        "-movflags", "+faststart",
        "-c:a", "aac", "-b:a", "128k",
        "-t", str(total_dur + 1),
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
