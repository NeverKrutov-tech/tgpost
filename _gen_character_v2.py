import json
import requests
import time
from PIL import Image
from io import BytesIO

# Generate Anekdotik character - proper hybrid Minion + CJ (dark skin, CJ features)
prompt = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 55555,
            "steps": 30,
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
            "text": "Anekdotik character: hybrid of Minion and Carl Johnson (CJ) from GTA San Andreas. Dark brown skin tone like CJ, muscular athletic build. Yellow Minion-style cylindrical body but with human proportions. Single large round goggle eye with thick black frame. Green bandana tied on forehead like CJ. Gold chain necklace thick. Black leather bomber jacket open over yellow body. Baggy blue jeans worn low. White Nike Air Force 1 sneakers. Confident street pose, arms crossed. Comedy club stage background, spotlight. 3D Pixar style render, highly detailed, 8k, masterpiece, character design, front view, full body",
            "clip": ["4", 1]
        }
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "blurry, low quality, ugly, deformed, bad anatomy, extra limbs, missing limbs, watermark, text, signature, realistic photo, human face, two eyes, normal human proportions, pale skin, white skin, light skin, no bandana, no chain, no jacket, no jeans, no sneakers, minion without CJ features, pure yellow minion",
            "clip": ["4", 1]
        }
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["3", 0], "vae": ["4", 2]}
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "anekdotik_char_v2", "images": ["8", 0]}
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
                    img.save("data/anekdotik_generated_v2.png")
                    print(f"Saved: data/anekdotik_generated_v2.png ({img.size})")
            break
    else:
        print("Timeout")