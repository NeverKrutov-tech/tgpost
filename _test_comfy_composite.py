import json
import requests
import time
from PIL import Image
from io import BytesIO
import base64

# 1. Generate background via local ComfyUI (SDXL)
prompt = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 25,
            "cfg": 7,
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
        "inputs": {"width": 1080, "height": 1920, "batch_size": 1}
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "comedy club stage, red velvet curtains, spotlight center stage, wooden floor, brick wall backdrop, warm amber lighting, professional stand-up comedy venue, 8k, photorealistic, highly detailed, no people, no text",
            "clip": ["4", 1]
        }
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "blurry, low quality, ugly, deformed, bad anatomy, cartoon, illustration, text, watermark, signature, character, person, people, audience, seats",
            "clip": ["4", 1]
        }
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "comfy_bg_stage", "images": ["8", 0]}
    }
}

r = requests.post("http://127.0.0.1:8188/prompt", json={"prompt": prompt}, timeout=30)
print("Queue:", r.json())

prompt_id = r.json().get("prompt_id")
if prompt_id:
    print(f"Waiting for {prompt_id}...")
    for _ in range(60):
        time.sleep(5)
        r = requests.get(f"http://127.0.0.1:8188/history/{prompt_id}", timeout=5)
        hist = r.json()
        if prompt_id in hist:
            outputs = hist[prompt_id].get("outputs", {})
            print("Done! Outputs:", json.dumps(outputs, indent=2))
            
            # Download the generated image
            if "9" in outputs and "images" in outputs["9"]:
                img_info = outputs["9"]["images"][0]
                filename = img_info["filename"]
                subfolder = img_info.get("subfolder", "")
                # Download via /view endpoint
                url = f"http://127.0.0.1:8188/view?filename={filename}&subfolder={subfolder}&type=output"
                img_r = requests.get(url, timeout=10)
                if img_r.status_code == 200:
                    bg = Image.open(BytesIO(img_r.content)).convert("RGBA")
                    print(f"Downloaded background: {bg.size}")
                    
                    # Load character sprite
                    char = Image.open("data/anekdotik_character.png").convert("RGBA")
                    print(f"Character: {char.size}")
                    
                    # Composite character on background (simple test)
                    # Scale character to ~65% of height
                    target_h = int(1920 * 0.65)
                    scale = target_h / char.height
                    new_w = int(char.width * scale)
                    char = char.resize((new_w, target_h), Image.Resampling.LANCZOS)
                    
                    # Position at bottom center
                    char_x = (1080 - new_w) // 2
                    char_y = 1920 - target_h + 60  # slightly raised
                    
                    # Composite
                    result = bg.copy()
                    result.paste(char, (char_x, char_y), char)
                    
                    # Save
                    result.save("data/test_composite.png")
                    print("Saved composite: data/test_composite.png")
            break
    else:
        print("Timeout")