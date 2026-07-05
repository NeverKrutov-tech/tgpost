import json
import requests
import time
from PIL import Image
from io import BytesIO

# Generate Anekdotik character via txt2img with detailed prompt
prompt = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 12345,
            "steps": 30,
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
        "inputs": {"width": 1024, "height": 1536, "batch_size": 1}
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "a unique cartoon character 'Anekdotik', hybrid of Minion and CJ from GTA San Andreas, yellow cylindrical body like Minion with single large goggle eye, black leather jacket like CJ, green bandana, gold chain necklace, baggy jeans, white sneakers, expressive face, confident pose, standing on comedy club stage, spotlight lighting, 3d render style, pixar quality, highly detailed, 8k, masterpiece, character design sheet, front view, full body",
            "clip": ["4", 1]
        }
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "blurry, low quality, ugly, deformed, bad anatomy, extra limbs, missing limbs, watermark, text, signature, realistic photo, human, realistic proportions, two eyes, normal human face",
            "clip": ["4", 1]
        }
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "anekdotik_char", "images": ["8", 0]}
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
            
            if "9" in outputs and "images" in outputs["9"]:
                img_info = outputs["9"]["images"][0]
                filename = img_info["filename"]
                subfolder = img_info.get("subfolder", "")
                url = f"http://127.0.0.1:8188/view?filename={filename}&subfolder={subfolder}&type=output"
                img_r = requests.get(url, timeout=10)
                if img_r.status_code == 200:
                    img = Image.open(BytesIO(img_r.content))
                    img.save("data/anekdotik_generated.png")
                    print(f"Saved: data/anekdotik_generated.png ({img.size})")
            break
    else:
        print("Timeout")