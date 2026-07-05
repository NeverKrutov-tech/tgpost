import json
import requests
import time

# Check available checkpoints
url = "http://127.0.0.1:8188/object_info/CheckpointLoaderSimple"
r = requests.get(url, timeout=5)
info = r.json()
print("Checkpoints:", info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0])

# Get system stats
r = requests.get("http://127.0.0.1:8188/system_stats", timeout=5)
print("System:", r.json())

# Test prompt (simple SD 1.5 generation)
prompt = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 12345,
            "steps": 20,
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
        "inputs": {"width": 512, "height": 512, "batch_size": 1}
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "a funny minion character, comedy club stage, cartoon style, high quality", "clip": ["4", 1]}
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "blurry, low quality, ugly, deformed", "clip": ["4", 1]}
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "test_comfy", "images": ["8", 0]}
    }
}

r = requests.post("http://127.0.0.1:8188/prompt", json={"prompt": prompt}, timeout=30)
print("Queue response:", r.json())

prompt_id = r.json()["prompt_id"]
print(f"Waiting for {prompt_id}...")

for _ in range(60):
    time.sleep(2)
    r = requests.get(f"http://127.0.0.1:8188/history/{prompt_id}", timeout=5)
    hist = r.json()
    if prompt_id in hist:
        outputs = hist[prompt_id].get("outputs", {})
        print("Done! Outputs:", json.dumps(outputs, indent=2))
        break
else:
    print("Timeout")