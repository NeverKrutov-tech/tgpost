import json, requests

# Check available checkpoints
url = "http://127.0.0.1:8188/object_info/CheckpointLoaderSimple"
r = requests.get(url, timeout=5)
print(r.json())