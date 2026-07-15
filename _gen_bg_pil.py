"""Generate cinematic backgrounds with PIL — no ML needed."""

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path("data/backgrounds")
OUT.mkdir(exist_ok=True)
W, H = 1080, 1920

random.seed(42)

# ── Color palettes per theme ─────────────────────────────

PALETTES = {
    "office": {
        "colors": [(210, 220, 235), (180, 195, 215), (140, 160, 190)],
        "accent": (70, 120, 180),
        "warm": False,
    },
    "hospital": {
        "colors": [(230, 240, 245), (200, 215, 225), (170, 190, 205)],
        "accent": (100, 180, 200),
        "warm": False,
    },
    "family": {
        "colors": [(220, 190, 160), (200, 165, 130), (180, 140, 100)],
        "accent": (200, 100, 60),
        "warm": True,
    },
    "army": {
        "colors": [(100, 110, 90), (120, 130, 105), (80, 90, 70)],
        "accent": (60, 75, 50),
        "warm": False,
    },
    "pub": {
        "colors": [(80, 50, 35), (100, 65, 45), (130, 90, 65)],
        "accent": (80, 40, 20),
        "warm": True,
    },
    "school": {
        "colors": [(195, 180, 150), (175, 160, 130), (210, 195, 170)],
        "accent": (140, 120, 80),
        "warm": True,
    },
    "animal": {
        "colors": [(230, 210, 180), (200, 180, 150), (250, 235, 210)],
        "accent": (180, 120, 60),
        "warm": True,
    },
    "money": {
        "colors": [(50, 55, 65), (65, 70, 85), (90, 95, 110)],
        "accent": (200, 170, 60),
        "warm": False,
    },
    "default": {
        "colors": [(180, 160, 130), (160, 140, 110), (200, 185, 160)],
        "accent": (120, 80, 50),
        "warm": True,
    },
}


def _gaussian(amp: float, center: float, sigma: float, x: float) -> float:
    return amp * math.exp(-((x - center) ** 2) / (2 * sigma ** 2))


def _draw_gradient(draw: ImageDraw, colors: list, warm: bool):
    """Draw a multi-stop gradient vertically with slight warm/cool variation."""
    for y in range(H):
        t = y / H
        idx_f = t * (len(colors) - 1)
        i = int(idx_f)
        frac = idx_f - i
        if i + 1 < len(colors):
            c = tuple(int(a + (b - a) * frac) for a, b in zip(colors[i], colors[i + 1]))
        else:
            c = colors[-1]
        draw.line([(0, y), (W, y)], fill=c)


def _add_bokeh(img: Image.Image, palette: dict, count: int = 30):
    """Add soft glowing circles (bokeh) for depth."""
    rng = random.Random(42)
    colors = palette["colors"]
    accent = palette["accent"]
    for _ in range(count):
        cx = rng.randint(0, W)
        cy = rng.randint(0, H)
        r = rng.randint(30, 200)
        c = colors[rng.randint(0, len(colors) - 1)]
        if rng.random() < 0.15:
            c = accent
        a = rng.randint(8, 30)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        ld.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(*c, a),
        )
        layer = layer.filter(ImageFilter.GaussianBlur(radius=15))
        img.paste(layer, (0, 0), layer)


def _add_light_rays(img: Image.Image, warm: bool):
    """Add subtle light rays from top."""
    rng = random.Random(123)
    base_color = (255, 230, 180) if warm else (220, 230, 255)
    for _ in range(3):
        x = rng.randint(W // 4, 3 * W // 4)
        angle = rng.uniform(-0.4, 0.4)
        length = rng.randint(400, 800)
        width = rng.randint(200, 400)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        for i in range(width):
            a = int(15 * (1 - i / width))
            if a < 1:
                continue
            off = int(math.tan(angle) * i)
            y1 = 0 + off
            y2 = length + off
            ld.line([(x - width // 2 + i, y1), (x - width // 2 + i, y2)], fill=(*base_color, a))
        layer = layer.filter(ImageFilter.GaussianBlur(radius=20))
        img.paste(layer, (0, 0), layer)


def _add_noise(img: Image.Image, intensity: int = 15):
    """Add subtle film grain."""
    rng = random.Random(99)
    noise = Image.new("RGBA", img.size, (0, 0, 0, 0))
    nd = ImageDraw.Draw(noise)
    for y in range(0, H, 2):
        for x in range(0, W, 2):
            v = rng.randint(-intensity, intensity)
            nd.point((x, y), fill=(v + 128, v + 128, v + 128, 30))
    img.paste(noise, (0, 0), noise)


def _add_vignette(img: Image.Image, strength: int = 100):
    """Darken edges."""
    vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    vd = ImageDraw.Draw(vignette)
    cx, cy = W // 2, H // 2
    max_r = math.sqrt(cx ** 2 + cy ** 2)
    for y in range(H):
        for x in range(W):
            d = math.sqrt((x - cx) ** 2 + (y - cx) ** 2)  # intentional slight off-center
            t = min(1.0, d / (max_r * 0.7))
            if t > 0:
                a = int(t * strength)
                if a > 0:
                    vd.point((x, y), fill=(0, 0, 0, a))
    img.paste(vignette, (0, 0), vignette)


def _add_texture_overlay(img: Image.Image, seed: int):
    """Add a subtle fabric/canvas texture."""
    rng = random.Random(seed)
    tex = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(tex)
    for y in range(0, H, 3):
        for x in range(0, W, 3):
            v = rng.randint(-5, 5)
            td.point((x, y), fill=(v + 128, v + 128, v + 128, 8))
    img.paste(tex, (0, 0), tex)


def generate_background(key: str, palette: dict) -> Path:
    """Generate one background image."""
    path = OUT / f"{key}.png"
    if path.exists():
        return path

    img = Image.new("RGBA", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    _draw_gradient(draw, palette["colors"], palette["warm"])
    _add_bokeh(img, palette, count=25)
    _add_light_rays(img, palette["warm"])
    _add_noise(img, intensity=12)
    _add_texture_overlay(img, seed=hash(key) % 10000)
    _add_vignette(img, strength=80)

    img = img.convert("RGB")
    img.save(path, quality=92)
    print(f"  {key}.png — saved ({path.stat().st_size // 1024} KB)")
    return path


def generate_all():
    print("Generating backgrounds with PIL...")
    count = 0
    for key, palette in PALETTES.items():
        generate_background(key, palette)
        count += 1
    print(f"\nDone! Generated {count}/{len(PALETTES)} backgrounds in {OUT}")


if __name__ == "__main__":
    generate_all()
