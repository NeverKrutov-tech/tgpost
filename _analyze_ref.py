from PIL import Image

# Analyze the Shedevrum reference (original working character)
ref = Image.open("data/anekdotik_character.png").convert("RGBA")
w, h = ref.size
px = ref.load()

print(f"Reference (current): {w}x{h}")

# Sample key regions
# Head area (top 30%)
head_colors = [px[x, int(h*0.12)] for x in range(0, w, 10)]
print(f"\nHead region (y={int(h*0.12)}):")
print(f"  Unique colors (sampled): {len(set(c[:3] for c in head_colors))}")

# Body area (middle)
body_colors = [px[x, int(h*0.5)] for x in range(0, w, 10)]
print(f"\nBody region (y={int(h*0.5)}):")
print(f"  Unique colors (sampled): {len(set(c[:3] for c in body_colors))}")

# Check for key Minion features
goggle_count = 0
yellow_count = 0
dark_skin_count = 0
for y in range(0, h, 4):
    for x in range(0, w, 4):
        r, g, b, a = px[x, y]
        if a < 10:  # transparent
            continue
        # Yellow (minion body)
        if r > 180 and g > 150 and b < 120:
            yellow_count += 1
        # Dark brown skin
        elif 50 < r < 140 and 30 < g < 100 and b < 60:
            dark_skin_count += 1
        # Dark round object (goggle eye)
        elif r < 40 and g < 40 and b < 40:
            goggle_count += 1

total = yellow_count + dark_skin_count + goggle_count
print(f"\nFeature analysis (non-transparent pixels):")
print(f"  Yellow (minion body): {yellow_count}")
print(f"  Dark skin (CJ face): {dark_skin_count}")
print(f"  Dark pixels (goggle/outlines): {goggle_count}")

# Analyze Shedevrum original dimensions
print(f"\nCharacter dimensions:")
print(f"  Width: {w}px")
print(f"  Height: {h}px")
print(f"  Aspect ratio: {w/h:.2f}")
