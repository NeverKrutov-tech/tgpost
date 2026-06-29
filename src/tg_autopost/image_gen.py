import colorsys
import os
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

if os.name == "nt":
    _FONT_CANDIDATES = [
        ("C:\\Windows\\Fonts\\Arial.ttf", "C:\\Windows\\Fonts\\Arialbd.ttf"),
    ]
else:
    _FONT_CANDIDATES = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]

FONT_PATH: str | None = None
FONT_BOLD_PATH: str | None = None
for regular, bold in _FONT_CANDIDATES:
    if Path(regular).exists():
        FONT_PATH = regular
        FONT_BOLD_PATH = bold if Path(bold).exists() else regular
        break
if FONT_PATH is None:
    raise RuntimeError("No suitable font found on this system")
OUTPUT_DIR = Path("data/images")
WIDTH = 1080
HEIGHT = 1080
PADDING = 80
LINE_HEIGHT_RATIO = 1.35
PARAGRAPH_SPACING = 0.6
TOP_MARGIN = 120
BOTTOM_MARGIN = 100
GRADIENT_STEPS = 60


def random_palette() -> dict:
    hue = random.uniform(0, 1)
    is_dark = random.random() < 0.6
    if is_dark:
        bg_l1, bg_l2 = random.uniform(0.06, 0.18), random.uniform(0.03, 0.12)
        accent_s, accent_l = random.uniform(0.4, 0.8), random.uniform(0.45, 0.65)
        text_l = random.uniform(0.85, 0.95)
    else:
        bg_l1, bg_l2 = random.uniform(0.85, 0.95), random.uniform(0.78, 0.90)
        accent_s, accent_l = random.uniform(0.4, 0.7), random.uniform(0.35, 0.55)
        text_l = random.uniform(0.08, 0.18)

    sat = random.uniform(0.04, 0.12)
    bg1 = tuple(int(c * 255) for c in colorsys.hls_to_rgb(hue, bg_l1, sat))
    bg2 = tuple(int(c * 255) for c in colorsys.hls_to_rgb(hue, bg_l2, sat))
    accent = tuple(int(c * 255) for c in colorsys.hls_to_rgb(hue, accent_l, accent_s))
    accent_dim = tuple(int(c * 255) for c in colorsys.hls_to_rgb(hue, accent_l * 0.7, accent_s * 0.6))
    text = tuple(int(c * 255) for c in colorsys.hls_to_rgb(hue, text_l, 0.0))

    headers = ["Анекдот дня", "Поржали", "Со дна юмора", "Смех без причины", "Жизненно", "За жизнь"]

    return {
        "bg_top": bg1,
        "bg_bot": bg2,
        "bg_hue": hue,
        "accent": accent,
        "accent_dim": accent_dim,
        "text": text,
        "header": random.choice(headers),
    }


def extract_header(text: str) -> str | None:
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("\u2014") or line.startswith("-"):
            return line[:60].rstrip(".,;:!?\u2026")
    return None


def make_gradient(color1: tuple, color2: tuple) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    strip_h = HEIGHT // GRADIENT_STEPS
    for i in range(GRADIENT_STEPS):
        t = i / (GRADIENT_STEPS - 1)
        r = int(color1[0] + (color2[0] - color1[0]) * t)
        g = int(color1[1] + (color2[1] - color1[1]) * t)
        b = int(color1[2] + (color2[2] - color1[2]) * t)
        y0 = i * strip_h
        y1 = HEIGHT if i == GRADIENT_STEPS - 1 else (i + 1) * strip_h
        draw.rectangle([(0, y0), (WIDTH, y1)], fill=(r, g, b))
    return img


def draw_dots(draw: ImageDraw.ImageDraw, color: tuple) -> None:
    for cx, cy in [(WIDTH - 40, 30), (WIDTH - 60, 30), (WIDTH - 80, 30)]:
        draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=color)
    for cx, cy in [(40, HEIGHT - 30), (60, HEIGHT - 30), (80, HEIGHT - 30)]:
        draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=color)


def draw_bg_pattern(draw: ImageDraw.ImageDraw, color: tuple) -> None:
    for r in [400, 500, 600]:
        draw.ellipse([WIDTH//2 - r, HEIGHT//2 - r, WIDTH//2 + r, HEIGHT//2 + r], outline=color, width=2)
    r = 200
    draw.ellipse([WIDTH - r, -r, WIDTH + r, r], outline=color, width=1)


def ensure_dir() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def pick_font_size(text: str, max_width: int, max_height: int) -> int:
    for font_size in range(64, 18, -2):
        font = ImageFont.truetype(FONT_PATH, font_size)
        lh = int(font_size * LINE_HEIGHT_RATIO)
        pg = int(font_size * PARAGRAPH_SPACING)
        total = 0
        paragraphs = text.split("\n\n")
        for pi, para in enumerate(paragraphs):
            for line in para.split("\n"):
                wrapped = wrap_text(line, font, max_width)
                total += len(wrapped) * lh
            if pi < len(paragraphs) - 1:
                total += pg
        if total <= max_height:
            return font_size
    return 18


def wrap_text(text: str, font: ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        if font.getlength(test) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def fits_in_image(text: str, min_font_size: int = 28) -> bool:
    return pick_font_size(text, WIDTH - PADDING * 2, HEIGHT - TOP_MARGIN - BOTTOM_MARGIN) >= min_font_size


def generate_joke_image(text: str, post_number: int, rubric_name: str | None = None) -> str:
    ensure_dir()

    tmpl = random_palette()
    img = make_gradient(tmpl["bg_top"], tmpl["bg_bot"])
    draw = ImageDraw.Draw(img)

    accent_color = tmpl["accent"]
    accent_dim = tmpl["accent_dim"]
    text_color = tmpl["text"]
    header_text = rubric_name or extract_header(text) or tmpl["header"]

    draw.rectangle([0, 0, WIDTH, 4], fill=accent_color)
    draw.rectangle([0, HEIGHT - 4, WIDTH, HEIGHT], fill=accent_color)
    draw_dots(draw, accent_dim)
    draw_bg_pattern(draw, accent_dim)

    try:
        header_font = ImageFont.truetype(FONT_BOLD_PATH, 36)
    except Exception:
        header_font = ImageFont.truetype(FONT_PATH, 36)

    header_w = header_font.getlength(header_text)
    draw.text(((WIDTH - header_w) / 2, 40), header_text, fill=accent_color, font=header_font)

    max_text_width = WIDTH - PADDING * 2
    max_text_height = HEIGHT - TOP_MARGIN - BOTTOM_MARGIN
    font_size = pick_font_size(text, max_text_width, max_text_height)
    font = ImageFont.truetype(FONT_PATH, font_size)
    line_height = int(font_size * LINE_HEIGHT_RATIO)
    para_gap = int(font_size * PARAGRAPH_SPACING)

    paragraphs = text.split("\n\n")
    wrapped = []
    total = 0
    for pi, para in enumerate(paragraphs):
        para_lines = []
        for line in para.split("\n"):
            para_lines.extend(wrap_text(line, font, max_text_width))
        wrapped.append(para_lines)
        total += len(para_lines) * line_height
        if pi < len(paragraphs) - 1:
            total += para_gap
    start_y = TOP_MARGIN + (max_text_height - total) // 2

    if wrapped:
        try:
            qfont = ImageFont.truetype(FONT_BOLD_PATH, 72)
        except Exception:
            qfont = ImageFont.truetype(FONT_PATH, 72)
        draw.text((PADDING, start_y - 10), "\u00AB", fill=accent_dim, font=qfont)

    y = start_y
    for pi, para_lines in enumerate(wrapped):
        for line in para_lines:
            line_width = font.getlength(line)
            draw.text(((WIDTH - line_width) // 2, y), line, fill=text_color, font=font)
            y += line_height
        if pi < len(wrapped) - 1:
            y += para_gap

    hash_val = abs(hash(text)) % 10_000_000
    filename = OUTPUT_DIR / f"joke_{hash_val}.jpg"
    img.save(filename, "JPEG", quality=92)
    return str(filename)


def generate_repost_card(text: str) -> str:
    ensure_dir()

    pal = random_palette()
    bg_color = pal["bg_top"]
    accent_color = pal["accent"]
    text_color = pal["text"]

    img = Image.new("RGB", (WIDTH, HEIGHT), bg_color)
    draw = ImageDraw.Draw(img)

    margin = 60
    inner = WIDTH - margin * 2
    draw.rounded_rectangle(
        [margin, 100, margin + inner, HEIGHT - 100],
        radius=24, fill=bg_color, outline=accent_color, width=3,
    )

    max_text_width = inner - 80
    max_text_height = HEIGHT - 280
    font_size = pick_font_size(text, max_text_width, max_text_height)
    if font_size < 24:
        font_size = 24
    font = ImageFont.truetype(FONT_PATH, font_size)
    line_height = int(font_size * LINE_HEIGHT_RATIO)
    para_gap = int(font_size * PARAGRAPH_SPACING)

    paragraphs = text.split("\n\n")
    wrapped = []
    total = 0
    for pi, para in enumerate(paragraphs):
        para_lines = []
        for line in para.split("\n"):
            para_lines.extend(wrap_text(line, font, max_text_width))
        wrapped.append(para_lines)
        total += len(para_lines) * line_height
        if pi < len(paragraphs) - 1:
            total += para_gap
    start_y = 160 + (max_text_height - total) // 2

    y = start_y
    for pi, para_lines in enumerate(wrapped):
        for line in para_lines:
            line_width = font.getlength(line)
            draw.text(((WIDTH - line_width) // 2, y), line, fill=text_color, font=font)
            y += line_height
        if pi < len(wrapped) - 1:
            y += para_gap

    try:
        wm_font = ImageFont.truetype(FONT_PATH, 24)
    except Exception:
        wm_font = ImageFont.truetype(FONT_PATH, 24)
    wm_text = "#анекдот #юмор"
    wm_w = wm_font.getlength(wm_text)
    draw.text(((WIDTH - wm_w) // 2, HEIGHT - 60), wm_text, fill=accent_color, font=wm_font)

    hash_val = abs(hash(text)) % 10_000_000
    filename = OUTPUT_DIR / f"card_{hash_val}.jpg"
    img.save(filename, "JPEG", quality=92)
    return str(filename)