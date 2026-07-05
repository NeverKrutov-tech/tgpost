import json
import requests
import time
from pathlib import Path

# IP-Adapter workflow for character consistency
# Uses the Anekdotik sprite as reference image

# First, let's check if IP-Adapter nodes are available
r = requests.get("http://127.0.0.1:8188/object_info", timeout=5)
nodes = r.json()
ipadapter_nodes = [k for k in nodes.keys() if "ipadapter" in k.lower() or "ip_adapter" in k.lower()]
print("IP-Adapter nodes:", ipadapter_nodes)

# Check for LoadImage nodes
loadimage_nodes = [k for k in nodes.keys() if "loadimage" in k.lower()]
print("LoadImage nodes:", loadimage_nodes)

# Check for ApplyStyleModel or similar
style_nodes = [k for k in nodes.keys() if "style" in k.lower() and "model" in k.lower()]
print("Style nodes:", style_nodes)