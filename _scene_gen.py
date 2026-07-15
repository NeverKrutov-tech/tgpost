"""Generate animated scene via ComfyUI AnimateDiff API"""
import json, time, requests, math, random, os, sys
from pathlib import Path

COMFY_URL = "http://127.0.0.1:8188"
OUTPUT_DIR = Path("data/scenes")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

def build_workflow(positive_prompt: str, negative_prompt: str = "",
                   width: int = 512, height: int = 768,
                   frames: int = 16, seed: int = -1,
                   steps: int = 20, cfg: float = 7.0):
    if seed < 0:
        seed = random.randint(0, 2**31)

    ckpt = "dreamshaper_8.safetensors"

    workflow = {
        "1": {  # Load Checkpoint
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": ckpt}
        },
        "2": {  # Empty Latent Image
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": frames}
        },
        "3": {  # Positive CLIP Text Encode
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive_prompt, "clip": ["1", 1]}
        },
        "4": {  # Negative CLIP Text Encode
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative_prompt, "clip": ["1", 1]}
        },
        "5": {  # AnimateDiff Loader
            "class_type": "AnimateDiffLoaderSimple",
            "inputs": {"model_name": "mm_sd_v15_v2.ckpt", "unmatch_n_models": False}
        },
        "6": {  # Apply AnimateDiff to model
            "class_type": "AnimateDiffModelLoader",
            "inputs": {"model": ["1", 0], "motion_module": ["5", 0]}
        },
        "7": {  # KSampler with AnimateDiff
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": 1.0,
                "model": ["6", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["2", 0]
            }
        },
        "8": {  # VAE Decode
            "class_type": "VAEDecode",
            "inputs": {"samples": ["7", 0], "vae": ["1", 2]}
        },
        "9": {  # Save as frames (PNG sequence)
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "anim_frame", "images": ["8", 0]}
        }
    }
    return workflow


def queue_prompt(workflow: dict, timeout: int = 300) -> list[str]:
    resp = requests.post(f"{COMFY_URL}/prompt",
                         json={"prompt": workflow}, timeout=30)
    data = resp.json()
    prompt_id = data["prompt_id"]
    print(f"Queued: {prompt_id}", flush=True)

    # Wait for completion
    start = time.time()
    while time.time() - start < timeout:
        hist = requests.get(f"{COMFY_URL}/history/{prompt_id}", timeout=10)
        hdata = hist.json()
        if prompt_id in hdata:
            outputs = hdata[prompt_id].get("outputs", {})
            images = []
            for node_id, node_out in outputs.items():
                for img_data in node_out.get("images", []):
                    images.append(img_data["filename"])
            print(f"Done! {len(images)} frames generated", flush=True)
            return images
        # Check queue
        q = requests.get(f"{COMFY_URL}/queue", timeout=5).json()
        remaining = q.get("queue_running", 0) + q.get("queue_pending", 0)
        elapsed = time.time() - start
        print(f"  Waiting... ({elapsed:.0f}s, queue: {remaining})", flush=True)
        time.sleep(5)
    raise TimeoutError("Generation timed out")


def generate_scene(positive_prompt: str, scene_name: str,
                   theme: str = "default", frames: int = 24,
                   **kwargs) -> bool:
    """Generate an animated scene and save as video."""
    # Scene type specific prompts
    theme_prompts = {
        "office": "office interior, desk, computer, professional atmosphere",
        "hospital": "hospital room, medical bed, clean white walls",
        "family": "cozy living room, warm lighting, home atmosphere",
        "army": "military barracks, uniformed soldiers, camp beds",
        "pub": "bar interior, wooden tables, beer glasses, dim lighting",
        "school": "classroom, desks, chalkboard, school supplies",
        "animal": "cozy room with pet, soft lighting",
        "money": "luxury office, city view, modern furniture",
        "default": "cozy room interior, warm ambient lighting"
    }
    bg_prompt = theme_prompts.get(theme, theme_prompts["default"])

    # Negative prompt
    neg = ("blurry, low quality, deformed, ugly, bad anatomy, "
           "extra limbs, bad hands, watermark, text, logo")

    full_prompt = f"{positive_prompt}, {bg_prompt}, animated scene, cinematic lighting, detailed, cartoon style, 2d animation style"  # noqa

    workflow = build_workflow(full_prompt, neg, frames=frames, **kwargs)

    print(f"\n=== Scene: {scene_name} ===")
    print(f"Prompt: {full_prompt[:120]}...")

    try:
        images = queue_prompt(workflow)
        # Copy frames to scene dir
        scene_dir = OUTPUT_DIR / scene_name
        scene_dir.mkdir(exist_ok=True)
        import shutil
        for img_name in images:
            src = Path("D:/Neiro/comfy/ComfyUI/output") / img_name
            if src.exists():
                shutil.copy2(src, scene_dir / img_name)
        print(f"Saved {len(images)} frames to {scene_dir}")
        return True
    except Exception as e:
        print(f"ERROR: {e}")
        return False


if __name__ == "__main__":
    # Test: generate one scene
    generate_scene(
        "a funny character telling a joke, expressive face, standing",
        "test_scene", theme="office", frames=8, seed=42, steps=15
    )
