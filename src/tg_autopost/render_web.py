import logging
import os
import threading

from flask import Flask, jsonify

from .config import load_settings
from .database import Database
from .handlers import PollingHandler, _api_call

app = Flask(__name__)
_bot_thread: threading.Thread | None = None
_handler: PollingHandler | None = None
_settings = None


def ensure_bot_started() -> None:
    global _bot_thread, _handler, _settings
    if _bot_thread and _bot_thread.is_alive():
        return
    _settings = load_settings()
    db = Database(_settings.database_url or _settings.database_path)
    _handler = PollingHandler(_settings, db)
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


@app.get("/debug")
def debug() -> tuple:
    ensure_bot_started()
    info = {"polling_alive": bool(_bot_thread and _bot_thread.is_alive())}
    if _settings is not None:
        me = _api_call(_settings.bot_token, "getMe", timeout=10)
        info["getMe"] = me.get("result") if me else None
        info["bot_token_present"] = bool(_settings.bot_token)
        info["channel_id"] = _settings.channel_id
        info["admin_id"] = _settings.admin_id
    return jsonify(info), 200


if __name__ == "__main__":
    ensure_bot_started()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
