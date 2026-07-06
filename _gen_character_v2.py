import json
import requests
import time
from PIL import Image, ImageFilter
from io import BytesIO

# Generate Anekdotik character - proper hybrid Minion + CJ (dark skin, CJ features)
# Using bright green background for easy chroma-key removal
prompt = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 33333,
            "steps": 35,
            "cfg": 8,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0]
        }
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 1024, "height": 1536, "batch_size": 1}
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "Minion character from Despicable Me but with dark brown skin on face and hands instead of yellow. Single large round black-rimmed mechanical goggle eye with thick strap around bald head. Yellow cylindrical body torso visible. Blue denim bib overalls with one shoulder strap hanging down, front pocket on bib. Dark brown skin face with confident smirk expression. Green bandana tied around forehead. Thick gold chain necklace. Short stubby legs in black work boots. Arms crossed cool pose. Front view full body. Pixar 3D style render, bright studio lighting, solid light gray background, highly detailed, 8k, masterpiece",
            "clip": ["4", 1]
        }
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "realistic human, normal human proportions, adult man, two eyes, symmetrical face, full lips, nose, ears, human hair, afro, dreadlocks, beard, moustache, muscular bodybuilder, skinny, fat, pale skin, white skin, light skin, pure yellow minion without dark skin, standard minion, no CJ features, no bandana, no chain, no overalls, complex background, watermark, text, signature, blurry, low quality, deformed, extra limbs, bad anatomy",
            "clip": ["4", 1]
        }
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "anekdotik_char_v6", "images": ["8", 0]}
    }
}

r = requests.post("http://127.0.0.1:8188/prompt", json={"prompt": prompt}, timeout=30)
print("Queue:", r.json())

prompt_id = r.json().get("prompt_id")
if prompt_id:
    print(f"Waiting for {prompt_id}...")
    for _ in range(120):
        time.sleep(5)
        r = requests.get(f"http://127.0.0.1:8188/history/{prompt_id}", timeout=5)
        hist = r.json()
        if prompt_id in hist:
            outputs = hist[prompt_id].get("outputs", {})
            print("Done! Outputs:", json.dumps(outputs, indent=2))

            if "9" in outputs and "images" in outputs["9"]:
                img_info = outputs["9"]["images"][0]
                filename = img_info["filename"]
                subfolder = img_info.get("subfolder", "")
                url = f"http://127.0.0.1:8188/view?filename={filename}&subfolder={subfolder}&type=output"
                img_r = requests.get(url, timeout=10)
                if img_r.status_code == 200:
                    # Remove background with rembg
                    from rembg import remove as rembg_remove
                    output_data = rembg_remove(img_r.content)
                    img = Image.open(BytesIO(output_data)).convert("RGBA")

                    # Crop tight + padding
                    bbox = img.getbbox()
                    if bbox:
                        pad = 30
                        img = img.crop((max(0, bbox[0]-pad), max(0, bbox[1]-pad),
                                        min(img.width, bbox[2]+pad), min(img.height, bbox[3]+pad)))

                    img.save("data/anekdotik_character.png")
                    print(f"Saved: data/anekdotik_character.png ({img.size})")
            break
    else:
        print("Timeout")