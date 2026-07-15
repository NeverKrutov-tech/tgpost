import json
import requests
import time
from PIL import Image
from io import BytesIO
from pathlib import Path

COMFY = "http://127.0.0.1:8188"
REF_IMAGE = "anekdotik_ref.png"
OUT_DIR = Path("data/poses")
OUT_DIR.mkdir(exist_ok=True)

POSES = [
    {
        "name": "neutral",
        "seed": 11111,
        "positive": "Minion character with dark brown skin face and hands, yellow cylindrical body, single large round goggle eye, blue denim bib overalls, green bandana on forehead, gold chain necklace, standing relaxed with arms at sides, front view full body, Pixar 3D style render, studio lighting, solid gray background",
    },
    {
        "name": "talking",
        "seed": 22222,
        "positive": "Minion character with dark brown skin face and hands, yellow cylindrical body, single large round goggle eye, blue denim bib overalls, green bandana on forehead, gold chain necklace, one hand raised gesturing while talking, expressive confident pose, front view full body, Pixar 3D style render, studio lighting, solid gray background",
    },
    {
        "name": "laughing",
        "seed": 33333,
        "positive": "Minion character with dark brown skin face and hands, yellow cylindrical body, single large round goggle eye, blue denim bib overalls, green bandana on forehead, gold chain necklace, both arms raised up in celebration, laughing happy expression, joyful pose, front view full body, Pixar 3D style render, studio lighting, solid gray background",
    },
    {
        "name": "pointing",
        "seed": 44444,
        "positive": "Minion character with dark brown skin face and hands, yellow cylindrical body, single large round goggle eye, blue denim bib overalls, green bandana on forehead, gold chain necklace, one arm extended to the side pointing, confident cool pose, front view full body, Pixar 3D style render, studio lighting, solid gray background",
    },
]

NEGATIVE = "realistic human, two eyes, normal human proportions, pale skin, white skin, pure yellow minion, no bandana, no chain, deformed, bad anatomy, extra limbs, blurry, low quality, watermark, text, signature, complex background"

# Base workflow nodes that are shared
BASE_NODES = {
    "1": {
        "class_type": "LoadImage",
        "inputs": {"image": REF_IMAGE},
    },
    "2": {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["1", 0], "vae": ["4", 2]},
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": NEGATIVE, "clip": ["4", 1]},
    },
    "7": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
    },
    "8": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "anekdotik_pose_", "images": ["7", 0]},
    },
}


def generate_pose(pose_info):
    name = pose_info["name"]
    print(f"\n=== Generating pose: {name} ===")

    # Build prompt with pose-specific nodes
    prompt = dict(BASE_NODES)

    # KSampler (img2img with denoise)
    prompt["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": pose_info["seed"],
            "steps": 30,
            "cfg": 7,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 0.65,
            "model": ["4", 0],
            "positive": ["5", 0],
            "negative": ["6", 0],
            "latent_image": ["2", 0],
        },
    }

    # Positive prompt
    prompt["5"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": pose_info["positive"], "clip": ["4", 1]},
    }

    # Change SaveImage prefix to include pose name
    prompt["8"]["inputs"]["filename_prefix"] = f"anekdotik_pose_{name}"

    r = requests.post(f"{COMFY}/prompt", json={"prompt": prompt}, timeout=30)
    resp = r.json()
    prompt_id = resp.get("prompt_id")
    print(f"  Queued: {prompt_id}")

    if not prompt_id:
        print(f"  FAILED: {resp}")
        return False

    # Wait for completion
    for _ in range(120):
        time.sleep(3)
        r = requests.get(f"{COMFY}/history/{prompt_id}", timeout=5)
        hist = r.json()
        if prompt_id in hist:
            status = hist[prompt_id].get("status", {})
            if status.get("completed"):
                outputs = hist[prompt_id].get("outputs", {})
                if "8" in outputs and "images" in outputs["8"]:
                    img_info = outputs["8"]["images"][0]
                    filename = img_info["filename"]
                    subfolder = img_info.get("subfolder", "")
                    url = f"{COMFY}/view?filename={filename}&subfolder={subfolder}&type=output"
                    img_r = requests.get(url, timeout=10)
                    if img_r.status_code == 200:
                        # Remove background with rembg
                        from rembg import remove as rembg_remove
                        output_data = rembg_remove(img_r.content)
                        img = Image.open(BytesIO(output_data)).convert("RGBA")

                        # Crop
                        bbox = img.getbbox()
                        if bbox:
                            pad = 30
                            img = img.crop((max(0, bbox[0]-pad), max(0, bbox[1]-pad),
                                            min(img.width, bbox[2]+pad), min(img.height, bbox[3]+pad)))

                        out_path = OUT_DIR / f"{name}.png"
                        img.save(out_path)
                        print(f"  Saved: {out_path} ({img.size})")
                        return True

            # Check for errors
            if status.get("status_str") == "error":
                print(f"  ERROR: {status}")
                return False

    print(f"  TIMEOUT")
    return False


# Generate all poses
for pose in POSES:
    success = generate_pose(pose)
    if not success:
        print(f"  Skipping remaining poses due to failure")
        break

print("\n=== Done ===")
