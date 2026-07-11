import html
import logging
import os
import threading
from pathlib import Path

import requests
from flask import Flask, jsonify

from .config import load_settings
from .database import Database
from .handlers import PollingHandler, _api_call

app = Flask(__name__)
_bot_thread: threading.Thread | None = None
_handler: PollingHandler | None = None
_settings = None


def _channel_username() -> str:
    if _settings is not None and _settings.channel_link:
        return _settings.channel_link.rstrip("/").rsplit("/", 1)[-1]
    return "Anetdodik"


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
    # ingest on startup so DB has some jokes for web routes
    try:
        from .app import run_ingest
        run_ingest()
    except Exception as exc:
        logging.getLogger(__name__).warning("Startup ingest skipped: %s", exc)


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
    if _handler is not None:
        info["poll_offset"] = _handler._offset
    if _settings is not None:
        info["bot_token_present"] = bool(_settings.bot_token)
        info["channel_id"] = _settings.channel_id
        info["admin_id"] = _settings.admin_id
        try:
            me = _api_call(_settings.bot_token, "getMe", timeout=10)
            info["getMe"] = me.get("result") if me else None
        except Exception as e:
            info["getMe_error"] = str(e)
        try:
            wh = _api_call(_settings.bot_token, "getWebhookInfo", timeout=10)
            if wh:
                whr = wh.get("result") or {}
                info["webhook_url"] = whr.get("url") or "(none)"
                info["webhook_pending"] = whr.get("pending_update_count", 0)
                info["webhook_cert"] = whr.get("has_custom_certificate", False)
                info["webhook_max"] = whr.get("max_connections")
                info["webhook_last_err"] = whr.get("last_error_message")
                info["webhook_last_err_date"] = whr.get("last_error_date")
        except Exception as e:
            info["webhook_err"] = str(e)
    return jsonify(info), 200


@app.post("/fix-webhook")
def fix_webhook() -> tuple:
    if _settings is None:
        return jsonify({"error": "not ready"}), 503
    result = _api_call(_settings.bot_token, "deleteWebhook", {"drop_pending_updates": True}, timeout=15)
    if result:
        return jsonify({"ok": True, "result": result.get("result")}), 200
    return jsonify({"ok": False}), 500


@app.get("/p/<int:msg_id>")
def post_card(msg_id: int) -> str:
    uname = _channel_username()
    post_url = f"https://t.me/{uname}/{msg_id}"
    channel_url = f"https://t.me/{uname}"
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Анекдот — @{uname}</title>
  <meta property="og:title" content="Анекдот из @{uname}">
  <meta property="og:description" content="Подпишись — каждый день свежие анекдоты и битвы!">
  <meta property="og:image" content="https://tgpost-bot-l4wq.onrender.com/img/{msg_id}">
  <meta property="og:url" content="{post_url}">
  <meta property="og:type" content="article">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="Анекдот из @{uname}">
  <meta name="twitter:description" content="Подпишись — каждый день свежие анекдоты и битвы!">
  <meta http-equiv="refresh" content="0;url={post_url}">
  <style>
    body {{ font-family: sans-serif; display: flex; justify-content: center; align-items: center;
           min-height: 100vh; margin: 0; background: #f5f5f5; }}
    .card {{ text-align: center; padding: 40px; background: white; border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.1); max-width: 400px; }}
    h1 {{ font-size: 20px; color: #333; }}
    p {{ color: #666; }}
    a {{ color: #0088cc; text-decoration: none; font-weight: bold; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Анекдот из @{uname}</h1>
    <p>Переходи в канал — там каждый день свежие анекдоты, битвы и конкурсы!</p>
    <a href="{post_url}">Открыть пост в Telegram →</a>
    <p><a href="{channel_url}">Подписаться на @{uname}</a></p>
  </div>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/avatar.png")
def avatar() -> tuple:
    """Fetch and cache channel avatar from Telegram API."""
    if _settings is None:
        return "", 503
    try:
        chat = _api_call(_settings.bot_token, "getChat", {"chat_id": _settings.channel_id}, timeout=10)
        if chat and chat.get("result", {}).get("photo"):
            file_id = chat["result"]["photo"]["big_file_id"] if isinstance(chat["result"]["photo"], dict) else chat["result"]["photo"]["big_file_id"]
            file_info = _api_call(_settings.bot_token, "getFile", {"file_id": file_id}, timeout=10)
            if file_info and file_info.get("result", {}).get("file_path"):
                url = f"https://api.telegram.org/file/bot{_settings.bot_token}/{file_info['result']['file_path']}"
                resp = requests.get(url, timeout=10)
                return resp.content, 200, {"Content-Type": "image/jpeg"}
    except Exception:
        pass
    # fallback: 1x1 transparent pixel
    return bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000"
                         "a49444154789c62600000000200011e608ed00000000049454e44ae426082"), 200, {"Content-Type": "image/png"}


@app.get("/top")
def top_weekly() -> str:
    uname = _channel_username()
    jokes_html = ""
    if _settings is not None:
        db = Database(_settings.database_url or _settings.database_path)
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT text, published_at FROM jokes WHERE published_at IS NOT NULL "
                "ORDER BY published_at DESC LIMIT 10"
            ).fetchall()
        if rows:
            for i, row in enumerate(rows, 1):
                text = row["text"].replace("\n", " ")[:200].rstrip() + "…" if len(row["text"]) > 200 else row["text"]
                jokes_html += f'<li><a href="https://t.me/{uname}">{html.escape(text)}</a></li>\n'
    if not jokes_html:
        jokes_html = "<li>Подпишись на @%s — там каждый день свежие анекдоты!</li>" % uname

    page = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Лучшие анекдоты — @{uname}</title>
  <meta name="description" content="Свежие анекдоты из Telegram канала @{uname}. Подпишись!">
  <meta property="og:title" content="Лучшие анекдоты — @{uname}">
  <meta property="og:description" content="Свежие анекдоты каждый день. Подпишись на @{uname}!">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary">
  <meta name="robots" content="index,follow">
  <style>
    body {{ font-family: sans-serif; max-width: 700px; margin: 0 auto; padding: 20px; background: #f5f5f5; }}
    h1 {{ color: #333; }}
    a {{ color: #0088cc; text-decoration: none; }}
    li {{ margin: 12px 0; line-height: 1.5; }}
    .sub {{ display: block; margin-top: 30px; padding: 15px; background: #0088cc; color: white;
            text-align: center; border-radius: 8px; font-size: 18px; }}
  </style>
</head>
<body>
  <h1>Анекдоты из @{uname}</h1>
  <p>Свежие анекдоты, битвы и конкурсы каждый день!</p>
  <ol>{jokes_html}</ol>
  <a class="sub" href="https://t.me/{uname}">Подписаться на @{uname} в Telegram</a>
</body>
</html>"""
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/img/<int:msg_id>")
def joke_image(msg_id: int) -> tuple:
    uname = _channel_username()
    # Generate a simple branded image — no DB query needed
    try:
        from .image_gen import generate_repost_card
        text = f"Свежий анекдот\nв Telegram\n\n@{uname}"
        output = generate_repost_card(text)
        with open(output, "rb") as f:
            data = f.read()
        Path(output).unlink(missing_ok=True)
        return data, 200, {"Content-Type": "image/png", "Cache-Control": "public, max-age=3600"}
    except Exception:
        return "", 500


if __name__ == "__main__":
    ensure_bot_started()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
