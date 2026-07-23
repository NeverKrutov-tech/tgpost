import sys, logging
logging.basicConfig(level=logging.INFO)
sys.path.insert(0, "src")
from tg_autopost.app import build_services
_, _, _, publisher = build_services()
ok = publisher._send_story()
print(f"Story posted: {ok}")
