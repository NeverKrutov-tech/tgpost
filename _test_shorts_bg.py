import json
import requests
import time

# Test with character-appropriate prompt for Shorts background
prompt = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 999,
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
        "inputs": {"width": 1024, "height": 1024, "batch_size": 1}
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "comedy club stage background, red curtain, spotlight, wooden floor, brick wall, warm lighting, cinematic, highly detailed, 4k, no characters, no text", "clip": ["4", 1]}
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "blurry, low quality, ugly, deformed, bad anatomy, cartoon, illustration, text, watermark, signature, character, person, people", "clip": ["4", 1]}
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "shorts_bg_test", "images": ["8", 0]}
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
            break
    else:
        print("Timeout")