# Try to install rembg
import subprocess
import sys

python = "D:\\Neiro\\comfy\\ComfyUI\\.venv\\Scripts\\python.exe"
pip_args = [python, "-m", "pip", "install", "rembg"]

print("Trying pip install rembg...")
try:
    result = subprocess.run(pip_args, capture_output=True, text=True, timeout=120)
    print("STDOUT:", result.stdout[-1000:])
    print("STDERR:", result.stderr[-1000:])
    print("Return code:", result.returncode)
except subprocess.TimeoutExpired:
    print("Timeout - network might be blocked")
except Exception as e:
    print(f"Error: {e}")
