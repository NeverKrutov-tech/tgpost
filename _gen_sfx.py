"""Generate sound effects with pure Python — no external deps."""

import math
import random
import struct
from pathlib import Path

SFX_DIR = Path("data/sfx")
SFX_DIR.mkdir(parents=True, exist_ok=True)
SR = 44100

rng = random.Random(42)


def _write_wav(path: Path, samples: list[float], sr: int = SR):
    peak = max(abs(s) for s in samples) or 1
    ints = [int(s / peak * 32767 * 0.9) for s in samples]
    with open(path, "wb") as f:
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


# ── Laugh track ──────────────────────────────────────────

def _laugh_cycle(t: float, pitch: float) -> float:
    """One 'ha' sound: quick attack, frequency rise, then decay."""
    cycle_t = t % 0.15
    env = max(0, 1 - cycle_t / 0.12)
    freq = pitch * (1 + 2 * cycle_t)
    return env * math.sin(2 * math.pi * freq * t)


def generate_laugh(duration: float = 3.0, num_persons: int = 3) -> list[float]:
    samples = [0.0] * int(duration * SR)
    persons = []
    for _ in range(num_persons):
        pitch = rng.uniform(180, 400)
        laugh_start = rng.uniform(0, 0.5)
        laugh_freq = rng.uniform(3, 6)
        persons.append((pitch, laugh_start, laugh_freq))

    for i in range(len(samples)):
        t = i / SR
        val = 0.0
        for pitch, start, freq in persons:
            if t < start:
                continue
            lt = t - start
            laugh_env = max(0, math.sin(math.pi * lt * freq))
            laugh_env = laugh_env ** 2
            val += _laugh_cycle(lt, pitch) * laugh_env * 0.4
        samples[i] = val
    return samples


# ── Applause ─────────────────────────────────────────────

def generate_applause(duration: float = 2.0) -> list[float]:
    n = int(duration * SR)
    samples = [0.0] * n
    for i in range(n):
        t = i / SR
        env = math.sin(math.pi * t / duration) ** 2
        env = env * env  # sharper attack/decay
        burst = rng.gauss(0, 1) * math.sqrt(abs(rng.gauss(0, 1)))
        samples[i] = env * burst * 0.3
    return samples


# ── Swoosh ────────────────────────────────────────────────

def generate_swoosh(duration: float = 0.5) -> list[float]:
    n = int(duration * SR)
    samples = [0.0] * n
    for i in range(n):
        t = i / SR
        env = math.sin(math.pi * t / duration) ** 4
        freq = 200 + 3000 * (t / duration)
        noise = rng.gauss(0, 1) * 0.5
        tone = math.sin(2 * math.pi * freq * t) * 0.3
        samples[i] = env * (noise + tone)
    return samples


# ── Hit ───────────────────────────────────────────────────

def generate_hit(duration: float = 0.15) -> list[float]:
    n = int(duration * SR)
    samples = [0.0] * n
    for i in range(n):
        t = i / SR
        env = math.exp(-t * 40)
        kick = math.sin(2 * math.pi * 60 * (1 - math.exp(-t * 20)) * t)
        noise = rng.gauss(0, 1) * math.exp(-t * 80) * 0.3
        click = math.sin(2 * math.pi * 3000 * t) * math.exp(-t * 200) * 0.4
        samples[i] = env * (kick * 0.7 + noise + click)
    return samples


# ── Generate all ──────────────────────────────────────────

def generate_all():
    sfx = {
        "laugh": (generate_laugh, 3.0),
        "applause": (generate_applause, 2.0),
        "swoosh": (generate_swoosh, 0.5),
        "hit": (generate_hit, 0.15),
    }
    for name, (gen_fn, dur) in sfx.items():
        path = SFX_DIR / f"{name}.wav"
        _write_wav(path, gen_fn(dur))
        kb = path.stat().st_size // 1024
        print(f"  {name}.wav — {kb} KB")

    print(f"\nAll SFX saved to {SFX_DIR}")


if __name__ == "__main__":
    generate_all()
