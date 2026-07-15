import requests, time, json
from pathlib import Path

COMFY = "http://127.0.0.1:8188"
OUT = Path("data/backgrounds")
OUT.mkdir(exist_ok=True)

BACKGROUNDS = [
    {
        "key": "office",
        "prompt": "cinematic wide shot of modern open-plan office interior, rows of desks with monitors, large panoramic windows with soft natural daylight streaming in, ergonomic chairs, potted plants, professional atmosphere, photorealistic, highly detailed, 8k, vertical portrait 9:16",
    },
    {
        "key": "hospital",
        "prompt": "cinematic wide shot of clean hospital corridor interior, white walls, medical equipment on carts, fluorescent ceiling lights reflecting on polished floor, sterile clinical atmosphere, photorealistic, highly detailed, 8k, vertical portrait 9:16",
    },
    {
        "key": "family",
        "prompt": "cinematic wide shot of cozy living room interior, warm amber lamp light, plush leather armchair, stone fireplace with crackling fire, family photos on walls, soft blankets on sofa, intimate warm atmosphere, photorealistic, highly detailed, 8k, vertical portrait 9:16",
    },
    {
        "key": "army",
        "prompt": "cinematic wide shot of military barracks interior, rows of metal bunk beds, camouflage netting, morning sunlight through dusty windows, footlockers at end of beds, tactical gear hanging, gritty authentic atmosphere, photorealistic, highly detailed, 8k, vertical portrait 9:16",
    },
    {
        "key": "pub",
        "prompt": "cinematic wide shot of traditional russian pub interior, dark wooden tables and benches, dim warm candlelight, vaulted brick ceiling, samovar on counter, bottles behind bar, rustic atmospheric, photorealistic, highly detailed, 8k, vertical portrait 9:16",
    },
    {
        "key": "school",
        "prompt": "cinematic wide shot of empty classroom interior, rows of wooden desks, large green chalkboard with chalk dust, sunlight streaming through tall windows, dust motes dancing in light beams, academic atmosphere, photorealistic, highly detailed, 8k, vertical portrait 9:16",
    },
    {
        "key": "animal",
        "prompt": "cinematic wide shot of sunlit bedroom interior, cat sleeping on windowsill, soft white curtains filtering golden afternoon light, cozy blankets on bed, peaceful domestic morning atmosphere, photorealistic, highly detailed, 8k, vertical portrait 9:16",
    },
    {
        "key": "money",
        "prompt": "cinematic wide shot of luxury corner office interior, floor-to-ceiling windows with panoramic city view, sleek modern black furniture, marble floor, ambient LED strip lighting, wealthy sophisticated atmosphere, photorealistic, highly detailed, 8k, vertical portrait 9:16",
    },
    {
        "key": "default",
        "prompt": "cinematic wide shot of cozy authentic russian dacha interior, wooden walls, warm stove, samovar on table, window with view of birch trees, soft afternoon light, comfortable rustic atmosphere, photorealistic, highly detailed, 8k, vertical portrait 9:16",
    },
]

NEG = "text, watermark, signature, people, person, human, cartoon, illustration, painting, blurry, low quality, deformed, distorted"

for bg in BACKGROUNDS:
    key = bg["key"]
    path = OUT / f"{key}.png"
    if path.exists():
        print(f"SKIP {key} (exists)")
        continue

    seed = hash(key) % 100000 + 10000
    prompt = {
        "1": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": 1080, "height": 1920, "batch_size": 1},
        },
        "2": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": 35, "cfg": 8,
                "sampler_name": "euler", "scheduler": "normal",
                "denoise": 1.0,
                "model": ["4", 0], "positive": ["5", 0],
                "negative": ["6", 0], "latent_image": ["1", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
        },
        "5": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": bg["prompt"], "clip": ["4", 1]},
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": NEG, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["2", 0], "vae": ["4", 2]},
        },
        "8": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"bg_{key}", "images": ["7", 0]},
        },
    }

    print(f"Generating {key} (seed {seed})...")
    r = requests.post(f"{COMFY}/prompt", json={"prompt": prompt}, timeout=30)
    pid = r.json().get("prompt_id")
    if not pid:
        print(f"  FAIL: {r.text}")
        continue

    for _ in range(180):
        time.sleep(3)
        r2 = requests.get(f"{COMFY}/history/{pid}", timeout=5)
        hist = r2.json()
        if pid in hist and hist[pid]["status"].get("completed"):
            outs = hist[pid]["outputs"]
            if "8" in outs and outs["8"]["images"]:
                info = outs["8"]["images"][0]
                url = f"{COMFY}/view?filename={info['filename']}&subfolder={info.get('subfolder','')}&type=output"
                img_r = requests.get(url, timeout=10)
                if img_r.status_code == 200:
                    path.write_bytes(img_r.content)
                    print(f"  Saved: {path} ({len(img_r.content)} bytes)")
            break
        if pid in hist and hist[pid]["status"].get("status_str") == "error":
            print(f"  ERROR: {hist[pid]['status']}")
            break
    else:
        print(f"  TIMEOUT")

print("\nDone!")
print(f"Generated: {len(list(OUT.glob('*.png')))}/{len(BACKGROUNDS)} backgrounds")
