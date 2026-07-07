import logging
import os
import threading

from flask import Flask

from .config import load_settings
from .database import Database
from .handlers import PollingHandler

app = Flask(__name__)
_bot_thread: threading.Thread | None = None
_handler: PollingHandler | None = None


def ensure_bot_started() -> None:
    global _bot_thread, _handler
    if _bot_thread and _bot_thread.is_alive():
        return
    settings = load_settings()
    db = Database(settings.database_url or settings.database_path)
    _handler = PollingHandler(settings, db)
    _bot_thread = threading.Thread(target=_handler.run_forever, daemon=True)
    _bot_thread.start()
    logging.getLogger(__name__).info("Render bot thread started")


@app.before_request
def _boot() -> None:
    ensure_bot_started()


@app.get("/")
def health() -> tuple[str, int]:
    ensure_bot_started()
    return "ok", 200


if __name__ == "__main__":
    ensure_bot_started()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
