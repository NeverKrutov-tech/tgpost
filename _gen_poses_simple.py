import json, requests, time, sys
from PIL import Image
from io import BytesIO
from pathlib import Path

COMFY = "http://127.0.0.1:8188"

POSE_NAME = sys.argv[1] if len(sys.argv) > 1 else "laughing"
SEED = int(sys.argv[2]) if len(sys.argv) > 2 else 55555
DENOISE = 0.65

PROMPTS = {
    "laughing": "Minion character with dark brown skin face and hands, yellow cylindrical body, single large round goggle eye, blue denim bib overalls, green bandana on forehead, gold chain necklace, both arms raised up in celebration, laughing happy expression, joyful pose, front view full body, Pixar 3D style render, studio lighting, solid gray background",
    "pointing": "Minion character with dark brown skin face and hands, yellow cylindrical body, single large round goggle eye, blue denim bib overalls, green bandana on forehead, gold chain necklace, one arm extended to the side pointing, confident cool pose, front view full body, Pixar 3D style render, studio lighting, solid gray background",
}

prompt = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "anekdotik_ref.png"}},
    "2": {"class_type": "VAEEncode", "inputs": {"pixels": ["1", 0], "vae": ["4", 2]}},
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": SEED, "steps": 30, "cfg": 7, "sampler_name": "euler",
            "scheduler": "normal", "denoise": DENOISE,
            "model": ["4", 0], "positive": ["5", 0], "negative": ["6", 0],
            "latent_image": ["2", 0],
        },
    },
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
    "5": {"class_type": "CLIPTextEncode", "inputs": {"text": PROMPTS[POSE_NAME], "clip": ["4", 1]}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "realistic human, two eyes, normal human proportions, pale skin, white skin, pure yellow minion, no bandana, no chain, deformed, bad anatomy, extra limbs, blurry, low quality, watermark, text, signature, complex background", "clip": ["4", 1]}},
    "7": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "8": {"class_type": "SaveImage", "inputs": {"filename_prefix": f"anekdotik_pose_{POSE_NAME}", "images": ["7", 0]}},
}

r = requests.post(f"{COMFY}/prompt", json={"prompt": prompt}, timeout=30)
pid = r.json().get("prompt_id")
print(f"Queued {POSE_NAME}: {pid}")

if pid:
    for _ in range(120):
        time.sleep(3)
        r2 = requests.get(f"{COMFY}/history/{pid}", timeout=5)
        hist = r2.json()
        if pid in hist:
            s = hist[pid]["status"]
            if s.get("completed"):
                outs = hist[pid]["outputs"]
                if "8" in outs and outs["8"]["images"]:
                    info = outs["8"]["images"][0]
                    url = f"{COMFY}/view?filename={info['filename']}&subfolder={info.get('subfolder','')}&type=output"
                    img_r = requests.get(url, timeout=10)
                    if img_r.status_code == 200:
                        from rembg import remove as rb
                        img = Image.open(BytesIO(rb(img_r.content))).convert("RGBA")
                        bbox = img.getbbox()
                        if bbox:
                            pad = 30
                            img = img.crop((max(0,bbox[0]-pad),max(0,bbox[1]-pad),min(img.width,bbox[2]+pad),min(img.height,bbox[3]+pad)))
                        out = Path(f"data/poses/{POSE_NAME}.png")
                        img.save(out)
                        print(f"Saved: {out} ({img.size})")
                break
            if s.get("status_str") == "error":
                print(f"Error: {s}")
                break
    else:
        print("Timeout")
