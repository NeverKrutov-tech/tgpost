import io
from PIL import Image
from rembg import remove
import sys

src = sys.argv[1] if len(sys.argv) > 1 else "D:\\Neiro\\comfy\\ComfyUI\\output\\anekdotik_char_v4_00001_.png"
dst = "data/anekdotik_character.png"

print(f"Processing: {src}")
try:
    with open(src, "rb") as f:
        input_data = f.read()
    output_data = remove(input_data)
    img = Image.open(io.BytesIO(output_data)).convert("RGBA")
    img.save(dst)
    print(f"Saved: {dst} ({img.size})")
    
    # Stats
    px = img.load()
    trans = sum(1 for y in range(img.height) for x in range(img.width) if px[x,y][3] < 10)
    total = img.width * img.height
    print(f"Transparent: {trans}/{total} ({100*trans//total}%)")
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
