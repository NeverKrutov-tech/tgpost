from PIL import Image, ImageFilter
import math

def extract_character_adaptive(src_path, dst_path):
    img = Image.open(src_path).convert("RGBA")
    w, h = img.size
    px = img.load()

    # Step 1: sample background colors from edges (top/bottom rows, left/right columns)
    bg_samples = []
    for x in range(0, w, 4):
        bg_samples.append(px[x, 0][:3])
        bg_samples.append(px[x, h-1][:3])
    for y in range(0, h, 4):
        bg_samples.append(px[0, y][:3])
        bg_samples.append(px[w-1, y][:3])

    # Step 2: find the most common background color range
    # Use simple approach: calculate per-pixel distance from nearest edge sample
    mask = Image.new("L", (w, h), 0)
    mask_px = mask.load()

    # For each pixel, check how different it is from the edge average
    avg_bg = tuple(sum(c[i] for c in bg_samples) // len(bg_samples) for i in range(3))
    print(f"Average edge color: RGB{avg_bg}")

    # Calculate standard deviation of edge colors to determine threshold
    variance = sum((c[i] - avg_bg[i])**2 for c in bg_samples for i in range(3)) / len(bg_samples)
    std_dev = math.sqrt(variance)
    thresh = max(30, min(80, int(std_dev * 3)))
    print(f"Edge std dev: {std_dev:.1f}, using threshold: {thresh}")

    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            dist = ((r - avg_bg[0])**2 + (g - avg_bg[1])**2 + (b - avg_bg[2])**2) ** 0.5
            if dist < thresh:
                mask_px[x, y] = 0  # background
            else:
                mask_px[x, y] = 255  # foreground

    # Clean up mask: remove small holes and smooth
    mask = mask.filter(ImageFilter.MedianFilter(size=5))
    mask = mask.filter(ImageFilter.SMOOTH_MORE)

    # Apply mask
    result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    result.paste(img, (0, 0), mask)

    # Crop tight + padding
    bbox = result.getbbox()
    if bbox:
        pad = 30
        result = result.crop((max(0, bbox[0]-pad), max(0, bbox[1]-pad),
                              min(w, bbox[2]+pad), min(h, bbox[3]+pad)))

    result.save(dst_path)
    print(f"Saved: {dst_path} ({result.size})")

    trans = sum(1 for y in range(result.height) for x in range(result.width) if result.getpixel((x,y))[3] < 10)
    total = result.width * result.height
    print(f"Transparent: {trans}/{total} ({100*trans//total}%)")

extract_character_adaptive("D:\\Neiro\\comfy\\ComfyUI\\output\\anekdotik_char_v3_00001_.png", "data/anekdotik_v3_clean.png")
extract_character_adaptive("D:\\Neiro\\comfy\\ComfyUI\\output\\anekdotik_char_v2_00001_.png", "data/anekdotik_v2_clean.png")
