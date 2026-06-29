import logging
import math
import random
import struct
import subprocess
import colorsys
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .image_gen import FONT_PATH

logger = logging.getLogger(__name__)

SHORTS_DIR = Path("data/shorts")
W, H = 1080, 1920
FPS = 24
PALETTES = [
    [(0.60, 0.85, 0.90), (0.70, 0.50, 0.95)],
    [(0.05, 0.85, 0.85), (0.30, 0.55, 0.85)],
    [(0.80, 0.75, 0.85), (0.95, 0.45, 0.75)],
    [(0.12, 0.80, 0.80), (0.50, 0.60, 0.85)],
    [(0.00, 0.70, 0.85), (0.10, 0.80, 0.90)],
    [(0.50, 0.90, 0.50), (0.55, 0.90, 0.50)],  # green
]


# ── helpers ──────────────────────────────────────────────────

def _hsl_rgb(h, s, l):
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return int(r * 255), int(g * 255), int(b * 255)


def _split_segments(text: str) -> list[str]:
    """Split into ~word-length segments for timed reveal."""
    words = text.split()
    segments, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= 40:
            cur = f"{cur} {w}".strip()
        else:
            segments.append(cur)
            cur = w
    if cur:
        segments.append(cur)
    return segments or [text]


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    path = FONT_PATH or "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    return ImageFont.truetype(str(path), size)


# ── audio generation ─────────────────────────────────────────

def _generate_beat(duration: float, output_path: Path,
                   bpm: int = 128, sr: int = 44100) -> None:
    """Generate a simple electronic beat loop as WAV."""
    beat_sec = 60.0 / bpm
    total_samples = int(duration * sr)
    samples = [0.0] * total_samples
    rng = random.Random(42)

    for i in range(total_samples):
        t = i / sr

        # kick drum
        kick_phase = (t % beat_sec) / beat_sec
        if kick_phase < 0.08:
            env = math.exp(-kick_phase * 80)
            samples[i] += 0.45 * env * math.sin(2 * math.pi * 55 * (1 + 3 * kick_phase) * t)

        # hi-hat (every 8th note)
        eighth = beat_sec / 2
        hat_phase = (t % eighth) / eighth
        if hat_phase < 0.04:
            env = math.exp(-hat_phase * 120)
            samples[i] += 0.12 * env * rng.gauss(0, 1)

        # pad chord (sustained)
        pad_note = 130.81  # C3
        if int(t // beat_sec) % 8 < 4:
            pad_freq = pad_note
        else:
            pad_freq = pad_note * 1.5  # G3
        pad_env = 0.06 * (1 - math.exp(-t * 0.5)) * max(0, 1 - (t / duration))
        samples[i] += pad_env * (
            0.5 * math.sin(2 * math.pi * pad_freq * t) +
            0.3 * math.sin(2 * math.pi * pad_freq * 2 * t)
        )

    # Normalise
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


def _generate_tts(text: str, output_path: Path) -> float:
    """Generate TTS audio, return duration in seconds."""
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


# ── frame rendering ──────────────────────────────────────────

def _render_gradient_strip(palette, shift: float) -> Image.Image:
    """Return a 1×H gradient strip."""
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


def _render_frame(t: float, total_dur: float,
                  segments: list[str], seg_times: list[tuple[float, float]],
                  seg_idx_map: dict, punchline_idx: int, palette: list,
                  particles: list[dict], font, punch_font, title_font
                  ) -> Image.Image:
    shift = t * 0.02

    strip = _render_gradient_strip(palette, shift)
    bg = strip.resize((W, H), Image.Resampling.BILINEAR)
    frame = bg.convert("RGBA")

    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    for p in particles:
        px = (p["x"] + t * p["vx"]) % W
        py = (p["y"] + t * p["vy"]) % H
        phase = t * p["freq"] + p["phase"]
        alpha = int((0.3 + 0.7 * max(0, math.sin(phase))) * 120)
        r = p["radius"]
        draw.ellipse([px - r, py - r, px + r, py + r],
                     fill=(255, 255, 255, alpha))

    visible_idx = [i for i, (st, et) in enumerate(seg_times) if st <= t <= et]

    if visible_idx:
        line_height = 130
        total_h = len(visible_idx) * line_height
        start_y = (H - total_h) // 2 + 50

        for j, idx in enumerate(visible_idx):
            y = start_y + j * line_height
            seg = segments[idx]
            st, et = seg_times[idx]
            local_t = max(0, t - st)
            is_punch = (idx == punchline_idx)
            fade = min(1.0, local_t / 0.35)

            if is_punch and fade > 0.6:
                font_use = punch_font
                color = (255, 220, 50, int(fade * 255))
                for dx, dy in [(-4, 0), (4, 0), (0, -4), (0, 4)]:
                    _center_text(draw, seg, W // 2 + dx, y + dy, font_use,
                                 (255, 200, 0, 80))
            else:
                font_use = font
                color = (255, 255, 255, int(fade * 255))

            _center_text(draw, seg, W // 2, y, font_use, color,
                         shadow=True, shadow_alpha=60)

    if t < 1.5:
        alpha = int(min(1.0, t / 0.4) * 255)
        if alpha > 0:
            _center_text(draw, "\u0410\u041d\u0415\u041a\u0414\u041e\u0422",
                         W // 2, H // 4, title_font,
                         (255, 255, 200, alpha), shadow=True, shadow_alpha=80)

    outro_start = total_dur - 2.5
    if t > outro_start:
        frac = min(1.0, (t - outro_start) / 0.5)
        alpha = int(frac * 255)
        if alpha > 0:
            _center_text(draw, "\u041f\u041e\u0414\u041f\u0418\u0428\u0418\u0421\u042c",
                         W // 2, H // 3, _get_font(100),
                         (255, 200, 50, alpha), shadow=True, shadow_alpha=80)
            _center_text(draw, "@Anetdodik",
                         W // 2, H // 3 + 140, _get_font(64),
                         (255, 255, 255, alpha), shadow=True, shadow_alpha=60)

    frame = Image.alpha_composite(frame, overlay)
    return frame.convert("RGB")


def _center_text(draw, text, x, y, font, fill, shadow=False,
                 shadow_alpha=60):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    bx = x - tw // 2
    by = y - th // 2
    if shadow:
        r, g, b, a = fill if len(fill) == 4 else (*fill, 255)
        for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, -5), (0, 5)]:
            draw.text((bx + dx, by + dy), text, font=font,
                      fill=(0, 0, 0, min(255, a * shadow_alpha // 100)))
    draw.text((bx, by), text, font=font, fill=fill)


# ── public ───────────────────────────────────────────────────

def render_short(joke_text: str, output_path: str) -> bool:
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)
    frame_dir = SHORTS_DIR / "frames"
    audio_dir = SHORTS_DIR / "audio"
    frame_dir.mkdir(exist_ok=True)
    audio_dir.mkdir(exist_ok=True)

    segments = _split_segments(joke_text)
    punch_idx = len(segments) - 1
    palette = random.choice(PALETTES)

    # Audio generation
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

    audio_dur = max(voice_dur, 12) + 3.0  # voice + outro padding
    total_dur = max(12, min(55, audio_dur))
    total_frames = int(total_dur * FPS)

    # Beat
    beat_path = audio_dir / "beat.wav"
    try:
        _generate_beat(total_dur, beat_path)
    except Exception as e:
        logger.error("Beat generation failed: %s", e)

    # Segment timings (proportional to char count)
    seg_lens = [len(s) for s in segments]
    total_chars = sum(seg_lens)
    padding_sec = 0.3
    seg_times = []
    cur = 2.0  # title
    for i, seg_len in enumerate(seg_lens):
        seg_dur = max(0.8, (seg_len / total_chars) * (voice_dur - 2.0))
        end = min(cur + seg_dur + padding_sec, total_dur - 3.0)
        seg_times.append((cur, end))
        cur = cur + seg_dur + padding_sec * 0.3

    # Fonts
    avg_len = sum(seg_lens) / max(1, len(seg_lens))
    base_size = 80 if avg_len < 20 else 64 if avg_len < 40 else 48
    font = _get_font(base_size)
    punch_font = _get_font(base_size + 20)
    title_font = _get_font(110)

    # Particles
    rng = random.Random(hash(joke_text) & 0xFFFFFFFF)
    particles = [
        {
            "x": rng.randint(0, W), "y": rng.randint(0, H),
            "vx": rng.uniform(-15, 15), "vy": rng.uniform(-25, -5),
            "radius": rng.randint(2, 5),
            "freq": rng.uniform(0.5, 2.0),
            "phase": rng.random() * math.tau,
        }
        for _ in range(30)
    ]

    logger.info("Rendering %d frames (%.1fs), %d segments, voice=%.1fs",
                total_frames, total_dur, len(segments), voice_dur)

    for f_idx in range(total_frames):
        t = f_idx / FPS
        img = _render_frame(
            t, total_dur,
            segments, seg_times, {}, punch_idx, palette,
            particles, font, punch_font, title_font,
        )
        img.save(frame_dir / f"f_{f_idx:06d}.png")

    # FFmpeg: image sequence + voice + beat
    voice_path = audio_dir / "voice.mp3"
    has_voice = voice_path.exists() and voice_path.stat().st_size > 100
    has_beat = beat_path.exists() and beat_path.stat().st_size > 100

    inputs = [
        "-framerate", str(FPS),
        "-i", str(frame_dir / "f_%06d.png"),
    ]
    filter_chains = []
    output_maps = []

    if has_voice and has_beat:
        inputs.extend(["-i", str(voice_path), "-i", str(beat_path)])
        filter_chains = [
            "[1:a]volume=1.5[a_voice]",
            "[2:a]volume=0.25[a_beat]",
            "[a_voice][a_beat]amix=inputs=2:duration=first[aout]",
        ]
        output_maps = ["-map", "[aout]"]
    elif has_voice:
        inputs.extend(["-i", str(voice_path)])
        filter_chains = ["[1:a]volume=1.5[aout]"]
        output_maps = ["-map", "[aout]"]
    elif has_beat:
        inputs.extend(["-i", str(beat_path)])
        filter_chains = ["[1:a]volume=0.3[aout]"]
        output_maps = ["-map", "[aout]"]
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
        logger.info("Rendered short: %s (%.1fs, %d frames)",
                    output_path, total_dur, total_frames)
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


# ── upload (unchanged) ──────────────────────────────────────

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
                "description": (
                    description + "\n\nПодпишись: https://t.me/Anetdodik"
                ).strip()[:5000],
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
