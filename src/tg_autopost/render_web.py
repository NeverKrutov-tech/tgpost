import html as html_mod
import logging
import os
import threading
from pathlib import Path

import requests
from flask import Flask, jsonify, abort, redirect

from .config import load_settings
from .database import Database
from .handlers import PollingHandler, _api_call
from .rubrics import RUBRICS

app = Flask(__name__)
_bot_thread: threading.Thread | None = None
_handler: PollingHandler | None = None
_settings = None
_BASE = "https://tgpost-bot-l4wq.onrender.com"


def _channel_username() -> str:
    if _settings is not None and _settings.channel_link:
        return _settings.channel_link.rstrip("/").rsplit("/", 1)[-1]
    return "Anetdodik"


def _share_urls(msg_id: int, text: str, uname: str) -> str:
    post_url = f"https://t.me/{uname}/{msg_id}"
    page_url = f"{_BASE}/p/{msg_id}"
    short_text = text.replace("\n", " ")[:100].strip()
    share_base = short_text + f"\n\n\U0001F923 \u0411\u043E\u043B\u044C\u0448\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u043E\u0432 \u0432 @{uname}"
    hashtags = "%23\u0430\u043D\u0435\u043A\u0434\u043E\u0442 %23\u044E\u043C\u043E\u0440 %23\u0441\u043C\u0435\u0445"
    tg = f"https://t.me/share/url?url={page_url}&text={html_mod.quote(share_base)}"
    tw = f"https://twitter.com/intent/tweet?text={html_mod.quote(share_base + ' ' + hashtags)}&url={page_url}"
    vk = f"https://vk.com/share.php?url={page_url}&title={html_mod.quote(share_base)}"
    wa = f"https://wa.me/?text={html_mod.quote(share_base + ' ' + page_url)}"
    fb = f"https://www.facebook.com/sharer/sharer.php?u={page_url}&quote={html_mod.quote(share_base)}"
    copy_btn = f'<button class="s cp" onclick="navigator.clipboard.writeText(\'{page_url}\').then(()=>this.textContent=\'\\u2705 \\u0421\\u043a\\u043e\\u043f\\u0438\\u0440\\u043e\\u0432\\u0430\\u043d\\u043e!\').catch(()=>this.textContent=\'\\u274c \\u041e\\u0448\\u0438\\u0431\\u043a\\u0430\')">\\uD83D\\uDCCB \\u041A\\u043E\\u043F\\u0438\\u0440\\u043E\\u0432\\u0430\\u0442\\u044C</button>'
    return f"""
    <div class="shares" style="margin-top:20px">
      <div style="font-size:12px;color:#888;margin-bottom:6px">\u041F\u043E\u0434\u0435\u043B\u0438\u0442\u044C\u0441\u044F \u0441 \u0434\u0440\u0443\u0437\u044C\u044F\u043C\u0438:</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <a href="{tg}" target="_blank" class="s tg">Telegram</a>
        <a href="{tw}" target="_blank" class="s tw">X</a>
        <a href="{vk}" target="_blank" class="s vk">VK</a>
        <a href="{wa}" target="_blank" class="s wa">WhatsApp</a>
        <a href="{fb}" target="_blank" class="s fb">Facebook</a>
        {copy_btn}
      </div>
    </div>"""


_STYLE = """
    body { font-family: -apple-system, sans-serif; max-width: 700px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
    h1 { color: #333; font-size: 22px; }
    a { color: #0088cc; text-decoration: none; }
    .joke { background: white; border-radius: 12px; padding: 24px; margin: 16px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.08); line-height: 1.6; white-space: pre-wrap; font-size: 16px; }
    .sub { display: block; margin-top: 20px; padding: 15px; background: #0088cc; color: white; text-align: center; border-radius: 8px; font-size: 18px; font-weight: bold; }
    .sub:hover { background: #0077b5; }
    .shares { display: flex; gap: 8px; flex-wrap: wrap; margin: 16px 0; }
    .s { padding: 8px 16px; border-radius: 6px; font-size: 14px; font-weight: bold; color: white !important; }
    .tg { background: #0088cc; }
    .tw { background: #1DA1F2; }
    .vk { background: #4A76A8; }
    .wa { background: #25D366; }
    .fb { background: #1877F2; }
    .cp { background: #555; cursor: pointer; border: none; font-size: 14px; font-weight: bold; color: white; padding: 8px 16px; border-radius: 6px; }
    .cp:hover { background: #444; }
    .meta { color: #888; font-size: 14px; text-align: center; margin: 12px 0; }
    .rubrics { display: flex; gap: 8px; flex-wrap: wrap; margin: 12px 0; }
    .rb { padding: 8px 14px; border-radius: 8px; background: white; color: #333 !important; font-size: 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.1); }
    .rb:hover { background: #0088cc; color: white !important; }
    .pagi { text-align: center; margin: 16px 0; color: #666; font-size: 14px; }
    .sticky-sub { position: fixed; bottom: 0; left: 0; right: 0; background: linear-gradient(135deg,#0088cc,#005f8a); color: white; padding: 12px 20px; display: flex; align-items: center; justify-content: space-between; z-index: 999; transform: translateY(100%); transition: transform 0.4s; box-shadow: 0 -4px 20px rgba(0,0,0,0.2); }
    .sticky-sub.show { transform: translateY(0); }
    .sticky-sub a { background: #fff; color: #0088cc; padding: 8px 20px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 15px; white-space: nowrap; }
    .sticky-sub span { font-size: 14px; margin-right: 10px; }
    .sticky-sub .close { cursor: pointer; opacity: 0.7; font-size: 20px; margin-left: 8px; }
    body { padding-bottom: 60px; }
    .footer { text-align: center; margin-top: 30px; color: #888; font-size: 14px; }
    li { margin: 12px 0; line-height: 1.5; }
"""


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
    try:
        from .app import run_ingest
        run_ingest()
    except Exception as exc:
        logging.getLogger(__name__).warning("Startup ingest skipped: %s", exc)


def _fetch_message_text(msg_id: int) -> str | None:
    if _settings is None:
        return None
    try:
        resp = _api_call(_settings.bot_token, "getMessage", {
            "chat_id": _settings.channel_id,
            "message_id": msg_id,
        }, timeout=10)
        if resp and resp.get("ok"):
            msg = resp["result"]
            text = msg.get("text") or msg.get("caption") or ""
            return text.strip() or None
    except Exception as e:
        logging.getLogger(__name__).warning("Failed to fetch message %s: %s", msg_id, e)
    return None


@app.before_request
def _boot() -> None:
    ensure_bot_started()


@app.get("/")
def home() -> tuple:
    ensure_bot_started()
    uname = _channel_username()
    channel_url = f"https://t.me/{uname}"
    jokes_html = ""
    if _settings is not None:
        db = Database(_settings.database_url or _settings.database_path)
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, text, published_at FROM jokes WHERE published_at IS NOT NULL "
                "ORDER BY published_at DESC LIMIT 5"
            ).fetchall()
        for row in rows:
            text = row["text"]
            jid = row["id"]
            display = text.replace("\n", " ")[:150].rstrip() + "\u2026" if len(text) > 150 else text
            jokes_html += f"""<li><a href="/joke/{jid}">{html_mod.escape(display)}</a></li>"""
    rubric_links = "".join(
        f'<a href="/rubric/{slug}" class="rb">{r["emoji"]} {r["name"]}</a>'
        for slug, r in [(k, RUBRICS[v]) for k, v in _RUBRIC_SLUGS.items()]
    )
    if not jokes_html:
        jokes_html = "<li>\u0421\u043A\u043E\u0440\u043E \u0431\u0443\u0434\u0443\u0442 \u043F\u0435\u0440\u0432\u044B\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B!</li>"
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>\u0410\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u0438\u0437 Telegram \u043A\u0430\u043D\u0430\u043B\u0430 @{uname}</title>
  <meta name="description" content="\u0421\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C \u0432 Telegram \u043A\u0430\u043D\u0430\u043B\u0435 @{uname}. \u042E\u043C\u043E\u0440, \u0431\u0438\u0442\u0432\u044B, \u043A\u043E\u043D\u043A\u0443\u0440\u0441\u044B \u0438 \u0442\u043E\u043B\u044C\u043A\u043E \u043B\u0443\u0447\u0448\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u0438\u0437 \u0438\u043D\u0442\u0435\u0440\u043D\u0435\u0442\u0430!">
  <meta property="og:title" content="\u0410\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u0438\u0437 @{uname}">
  <meta property="og:description" content="\u0421\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C. \u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C \u043D\u0430 @{uname}!">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{_BASE}/">
  <meta name="twitter:card" content="summary">
  <meta name="robots" content="index,follow">
  <link rel="canonical" href="{_BASE}/">
  <link rel="alternate" type="application/rss+xml" title="@{uname} RSS" href="{_BASE}/rss.xml">
  <style>{_STYLE}</style>
</head>
<body>
  <h1>\U0001F923 \u0410\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u0438\u0437 @{uname}</h1>
  <p>\u041B\u0443\u0447\u0448\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B, \u0438\u0441\u0442\u043E\u0440\u0438\u0438 \u0438 \u0431\u0430\u044F\u043D\u044B \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C \u0432 Telegram. \u0411\u0438\u0442\u0432\u044B, \u043A\u043E\u043D\u043A\u0443\u0440\u0441\u044B, \u0438\u043D\u0442\u0435\u0440\u0430\u043A\u0442\u0438\u0432! \u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C \u0438 \u043D\u0435 \u043F\u0440\u043E\u043F\u0443\u0441\u0442\u0438 \u043D\u0438 \u043E\u0434\u043D\u043E\u0439 \u0448\u0443\u0442\u043A\u0438.</p>
  <h2>\u0420\u0443\u0431\u0440\u0438\u043A\u0438</h2>
  <div class="rubrics">{rubric_links}</div>
  <h2>\u041F\u043E\u0441\u043B\u0435\u0434\u043D\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B</h2>
  <ol>{jokes_html}</ol>
  <a class="sub" href="{channel_url}">\U0001F514 \u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F \u043D\u0430 @{uname}</a>
  <p class="footer"><a href="/top">\u0412\u0441\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B</a> \u2022 <a href="/search">\u041F\u043E\u0438\u0441\u043A</a> \u2022 <a href="/widget">\u0412\u0438\u0434\u0436\u0435\u0442</a> \u2022 <a href="/rss.xml">RSS</a> \u2022 <a href="/sitemap.xml">\u041A\u0430\u0440\u0442\u0430 \u0441\u0430\u0439\u0442\u0430</a></p>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


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
def post_card(msg_id: int) -> tuple:
    uname = _channel_username()
    post_url = f"https://t.me/{uname}/{msg_id}"
    channel_url = f"https://t.me/{uname}"
    page_url = f"{_BASE}/p/{msg_id}"
    joke_text = _fetch_message_text(msg_id) or f"\u0421\u0432\u0435\u0436\u0438\u0439 \u0430\u043D\u0435\u043A\u0434\u043E\u0442 \u0438\u0437 @{uname}"
    og_desc = joke_text.replace("\n", " ")[:200].strip()
    safe_text = html_mod.escape(joke_text)
    shares = _share_urls(msg_id, joke_text, uname)
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>\u0410\u043D\u0435\u043A\u0434\u043E\u0442 \u0438\u0437 @{uname}</title>
  <meta name="description" content="{og_desc}">
  <meta property="og:title" content="\u0410\u043D\u0435\u043A\u0434\u043E\u0442 \u0438\u0437 @{uname}">
  <meta property="og:description" content="{og_desc}">
  <meta property="og:image" content="{_BASE}/img/{msg_id}">
  <meta property="og:url" content="{page_url}">
  <meta property="og:type" content="article">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="\u0410\u043D\u0435\u043A\u0434\u043E\u0442 \u0438\u0437 @{uname}">
  <meta name="twitter:description" content="{og_desc}">
  <meta name="robots" content="index,follow">
  <link rel="canonical" href="{page_url}">
  <style>{_STYLE}</style>
</head>
<body>
  <h1>\U0001F923 \u0410\u043D\u0435\u043A\u0434\u043E\u0442 \u0438\u0437 @{uname}</h1>
  <div class="joke">{safe_text}</div>
  {shares}
  <a class="sub" href="{channel_url}">\U0001F514 \u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F \u043D\u0430 @{uname}</a>
  <p class="meta"><a href="{post_url}">\u041E\u0442\u043A\u0440\u044B\u0442\u044C \u0432 Telegram \u2192</a></p>
  <p class="footer"><a href="/">\u041D\u0430 \u0433\u043B\u0430\u0432\u043D\u0443\u044E</a> \u2022 <a href="/search">\u041F\u043E\u0438\u0441\u043A</a> \u2022 <a href="/widget">\u0412\u0438\u0434\u0436\u0435\u0442</a> \u2022 <a href="/rss.xml">RSS</a></p>
  <div class="sticky-sub" id="stickySub">
    <span>\U0001F514 \u041F\u043E\u043D\u0440\u0430\u0432\u0438\u043B\u043E\u0441\u044C? \u0412 Telegram \u0435\u0449\u0451 \u0431\u043E\u043B\u044C\u0448\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u043E\u0432!</span>
    <div style="display:flex;align-items:center">
      <a href="{channel_url}" target="_blank">\u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F</a>
      <span class="close" onclick="document.getElementById('stickySub').classList.remove('show')">\u2716</span>
    </div>
  </div>
  <div id="exitPopup" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:9999;display:none;align-items:center;justify-content:center">
    <div style="background:white;border-radius:16px;padding:30px;max-width:360px;text-align:center;box-shadow:0 10px 40px rgba(0,0,0,0.3)">
      <div style="font-size:48px;margin-bottom:10px">\U0001F514</div>
      <h2 style="margin:0 0 8px;color:#333;font-size:20px">\u0423\u0436\u0435 \u0443\u0445\u043E\u0434\u0438\u0442\u0435?</h2>
      <p style="color:#666;margin:0 0 16px;font-size:15px">\u0412 Telegram \u043A\u0430\u043D\u0430\u043B\u0435 \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C \u0441\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B, \u0431\u0438\u0442\u0432\u044B \u0438 \u043A\u043E\u043D\u043A\u0443\u0440\u0441\u044B!</p>
      <a href="{channel_url}" target="_blank" style="display:block;padding:12px;background:#0088cc;color:white;border-radius:8px;text-decoration:none;font-size:16px;font-weight:bold">\U0001F514 \u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F</a>
      <button onclick="document.getElementById('exitPopup').style.display='none'" style="margin-top:10px;border:none;background:none;color:#888;cursor:pointer;font-size:14px">\u041F\u0440\u043E\u0434\u043E\u043B\u0436\u0438\u0442\u044C \u0447\u0442\u0435\u043D\u0438\u0435</button>
    </div>
  </div>
  <script>
    setTimeout(function(){{ document.getElementById('stickySub').classList.add('show'); }}, 3000);
    window.addEventListener('scroll', function(){{
      if (window.scrollY > 300) document.getElementById('stickySub').classList.add('show');
    }});
    document.addEventListener('mouseleave', function(e){{
      if (e.clientY < 0 && !localStorage.getItem('exitShown')) {{
        localStorage.setItem('exitShown', '1');
        document.getElementById('exitPopup').style.display = 'flex';
      }}
    }});
    document.addEventListener('copy', function(e){{
      var t = window.getSelection().toString();
      if (t.length > 30) {{
        e.clipboardData.setData('text/plain', t + '\\n\\n\u2014 \u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C: {channel_url}');
        e.preventDefault();
      }}
    }});
  </script>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/share/<int:msg_id>")
def share_redirect(msg_id: int) -> tuple:
    uname = _channel_username()
    page_url = f"{_BASE}/p/{msg_id}"
    joke_text = _fetch_message_text(msg_id) or ""
    short_text = joke_text.replace("\n", " ")[:100].strip()
    share_text = short_text + f"\n\n\U0001F923 \u0411\u043E\u043B\u044C\u0448\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u043E\u0432 \u0432 @{uname}"
    tg_url = f"https://t.me/share/url?url={page_url}&text={html_mod.quote(share_text)}"
    return redirect(tg_url), 302


@app.get("/img/<int:msg_id>")
def joke_image(msg_id: int) -> tuple:
    joke_text = _fetch_message_text(msg_id)
    if not joke_text:
        uname = _channel_username()
        joke_text = f"\u0421\u0432\u0435\u0436\u0438\u0439 \u0430\u043D\u0435\u043A\u0434\u043E\u0442 \u0432 Telegram\n\n@{uname}"
    try:
        from .image_gen import generate_repost_card
        output = generate_repost_card(joke_text)
        with open(output, "rb") as f:
            data = f.read()
        Path(output).unlink(missing_ok=True)
        return data, 200, {"Content-Type": "image/jpeg", "Cache-Control": "public, max-age=3600"}
    except Exception:
        return "", 500


@app.get("/img/joke/<int:joke_id>")
def joke_image_by_id(joke_id: int) -> tuple:
    ensure_bot_started()
    if _settings is None:
        return "", 503
    db = Database(_settings.database_url or _settings.database_path)
    row = db.get_joke_by_id(joke_id)
    joke_text = row["text"] if row else ""
    if not joke_text:
        return "", 404
    try:
        from .image_gen import generate_repost_card
        output = generate_repost_card(joke_text)
        with open(output, "rb") as f:
            data = f.read()
        Path(output).unlink(missing_ok=True)
        return data, 200, {"Content-Type": "image/jpeg", "Cache-Control": "public, max-age=3600"}
    except Exception:
        return "", 500


@app.get("/joke/<int:joke_id>")
def joke_page(joke_id: int) -> tuple:
    ensure_bot_started()
    if _settings is None:
        return abort(503)
    uname = _channel_username()
    channel_url = f"https://t.me/{uname}"
    db = Database(_settings.database_url or _settings.database_path)
    row = db.get_joke_by_id(joke_id)
    if not row or row.get("published_at") is None:
        abort(404)
    text = row["text"]
    first_line = text.split("\n")[0][:70].strip()
    title = f"\u0410\u043D\u0435\u043A\u0434\u043E\u0442: {first_line}\u2026" if len(first_line) >= 70 else f"\u0410\u043D\u0435\u043A\u0434\u043E\u0442: {first_line}"
    og_desc = text.replace("\n", " ")[:200].strip()
    safe_text = html_mod.escape(text)
    telegram_msg_id = row.get("telegram_msg_id")
    post_url = f"https://t.me/{uname}/{telegram_msg_id}" if telegram_msg_id else channel_url
    page_url = f"{_BASE}/joke/{joke_id}"
    shares = _share_urls_joke(joke_id, text, uname, telegram_msg_id)
    pub_date = row["published_at"]
    # related jokes
    related = ""
    try:
        with db.connect() as c:
            rel_rows = c.execute(
                "SELECT id, text FROM jokes WHERE id != ? AND published_at IS NOT NULL ORDER BY RANDOM() LIMIT 3",
                (joke_id,),
            ).fetchall()
        for r in rel_rows:
            short = r["text"].replace("\n", " ")[:100].strip()
            related += f'<li><a href="/joke/{r["id"]}">{html_mod.escape(short)}\u2026</a></li>'
    except Exception:
        pass
    schema = f"""{{
  "@context": "https://schema.org",
  "@type": "Article",
  "headline": "{html_mod.escape(first_line)}",
  "description": "{html_mod.escape(og_desc)}",
  "author": {{ "@type": "Organization", "name": "@{uname}" }},
  "datePublished": "{pub_date}"
}}"""
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{html_mod.escape(title)} — @{uname}</title>
  <meta name="description" content="{og_desc}">
  <meta property="og:title" content="{html_mod.escape(title)}">
  <meta property="og:description" content="{og_desc}">
  <meta property="og:image" content="{_BASE}/img/joke/{joke_id}">
  <meta property="og:url" content="{page_url}">
  <meta property="og:type" content="article">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{html_mod.escape(title)}">
  <meta name="twitter:description" content="{og_desc}">
  <meta name="robots" content="index,follow">
  <link rel="canonical" href="{page_url}">
  <style>{_STYLE}</style>
  <script type="application/ld+json">{schema}</script>
</head>
<body>
  <h1>\U0001F923 {html_mod.escape(first_line)}</h1>
  <div class="joke">{safe_text}</div>
  {shares}
  <p style="text-align:center;margin:10px 0"><a href="/img/joke/{joke_id}" class="s" style="background:#555;display:inline-block" download target="_blank">\U0001F4F7 \u0421\u043A\u0430\u0447\u0430\u0442\u044C \u043A\u0430\u0440\u0442\u0438\u043D\u043A\u0443</a></p>
  <a class="sub" href="{channel_url}">\U0001F514 \u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F \u043D\u0430 @{uname}</a>
  <p class="meta"><a href="{post_url}">\u041E\u0442\u043A\u0440\u044B\u0442\u044C \u0432 Telegram \u2192</a></p>
  <h2>\u0415\u0449\u0451 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B</h2>
  <ol>{related}</ol>
  <p class="footer"><a href="/">\u041D\u0430 \u0433\u043B\u0430\u0432\u043D\u0443\u044E</a> \u2022 <a href="/top">\u041B\u0443\u0447\u0448\u0438\u0435</a> \u2022 <a href="/search">\u041F\u043E\u0438\u0441\u043A</a> \u2022 <a href="/rss.xml">RSS</a></p>
  <div class="sticky-sub" id="stickySub">
    <span>\U0001F514 \u041F\u043E\u043D\u0440\u0430\u0432\u0438\u043B\u043E\u0441\u044C? \u0412 Telegram \u0435\u0449\u0451 \u0431\u043E\u043B\u044C\u0448\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u043E\u0432!</span>
    <div style="display:flex;align-items:center">
      <a href="{channel_url}" target="_blank">\u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F</a>
      <span class="close" onclick="document.getElementById('stickySub').classList.remove('show')">\u2716</span>
    </div>
  </div>
  <div id="exitPopup" style="position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.6);z-index:9999;display:none;align-items:center;justify-content:center">
    <div style="background:white;border-radius:16px;padding:30px;max-width:360px;text-align:center;box-shadow:0 10px 40px rgba(0,0,0,0.3)">
      <div style="font-size:48px;margin-bottom:10px">\U0001F514</div>
      <h2 style="margin:0 0 8px;color:#333;font-size:20px">\u0423\u0436\u0435 \u0443\u0445\u043E\u0434\u0438\u0442\u0435?</h2>
      <p style="color:#666;margin:0 0 16px;font-size:15px">\u0412 Telegram \u043A\u0430\u043D\u0430\u043B\u0435 \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C \u0441\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B, \u0431\u0438\u0442\u0432\u044B \u0438 \u043A\u043E\u043D\u043A\u0443\u0440\u0441\u044B!</p>
      <a href="{channel_url}" target="_blank" style="display:block;padding:12px;background:#0088cc;color:white;border-radius:8px;text-decoration:none;font-size:16px;font-weight:bold">\U0001F514 \u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F</a>
      <button onclick="document.getElementById('exitPopup').style.display='none'" style="margin-top:10px;border:none;background:none;color:#888;cursor:pointer;font-size:14px">\u041F\u0440\u043E\u0434\u043E\u043B\u0436\u0438\u0442\u044C \u0447\u0442\u0435\u043D\u0438\u0435</button>
    </div>
  </div>
  <script>
    setTimeout(function(){{ document.getElementById('stickySub').classList.add('show'); }}, 3000);
    window.addEventListener('scroll', function(){{
      if (window.scrollY > 300) document.getElementById('stickySub').classList.add('show');
    }});
    document.addEventListener('mouseleave', function(e){{
      if (e.clientY < 0 && !localStorage.getItem('exitShown')) {{
        localStorage.setItem('exitShown', '1');
        document.getElementById('exitPopup').style.display = 'flex';
      }}
    }});
    document.addEventListener('copy', function(e){{
      var t = window.getSelection().toString();
      if (t.length > 30) {{
        e.clipboardData.setData('text/plain', t + '\\n\\n\u2014 \u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C: {channel_url}');
        e.preventDefault();
      }}
    }});
  </script>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


def _share_urls_joke(joke_id: int, text: str, uname: str, telegram_msg_id: int | None) -> str:
    page_url = f"{_BASE}/joke/{joke_id}"
    short_text = text.replace("\n", " ")[:100].strip()
    share_base = short_text + f"\n\n\U0001F923 \u0411\u043E\u043B\u044C\u0448\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u043E\u0432 \u0432 @{uname}"
    hashtags = "%23\u0430\u043D\u0435\u043A\u0434\u043E\u0442 %23\u044E\u043C\u043E\u0440 %23\u0441\u043C\u0435\u0445"
    tg = f"https://t.me/share/url?url={page_url}&text={html_mod.quote(share_base)}"
    tw = f"https://twitter.com/intent/tweet?text={html_mod.quote(share_base + ' ' + hashtags)}&url={page_url}"
    vk = f"https://vk.com/share.php?url={page_url}&title={html_mod.quote(share_base)}"
    wa = f"https://wa.me/?text={html_mod.quote(share_base + ' ' + page_url)}"
    fb = f"https://www.facebook.com/sharer/sharer.php?u={page_url}&quote={html_mod.quote(share_base)}"
    return f"""
    <div class="shares" style="margin-top:20px">
      <div style="font-size:12px;color:#888;margin-bottom:6px">\u041F\u043E\u0434\u0435\u043B\u0438\u0442\u044C\u0441\u044F \u0441 \u0434\u0440\u0443\u0437\u044C\u044F\u043C\u0438:</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <a href="{tg}" target="_blank" class="s tg">Telegram</a>
        <a href="{tw}" target="_blank" class="s tw">X</a>
        <a href="{vk}" target="_blank" class="s vk">VK</a>
        <a href="{wa}" target="_blank" class="s wa">WhatsApp</a>
        <a href="{fb}" target="_blank" class="s fb">Facebook</a>
      </div>
    </div>"""


@app.get("/avatar.png")
def avatar() -> tuple:
    if _settings is None:
        return "", 503
    try:
        chat = _api_call(_settings.bot_token, "getChat", {"chat_id": _settings.channel_id}, timeout=10)
        if chat and chat.get("result", {}).get("photo"):
            photo = chat["result"]["photo"]
            file_id = photo.get("big_file_id") if isinstance(photo, dict) else photo.get("big_file_id")
            if file_id:
                file_info = _api_call(_settings.bot_token, "getFile", {"file_id": file_id}, timeout=10)
                if file_info and file_info.get("result", {}).get("file_path"):
                    url = f"https://api.telegram.org/file/bot{_settings.bot_token}/{file_info['result']['file_path']}"
                    resp = requests.get(url, timeout=10)
                    return resp.content, 200, {"Content-Type": "image/jpeg"}
    except Exception:
        pass
    return bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000"
                         "a49444154789c62600000000200011e608ed00000000049454e44ae426082"), 200, {"Content-Type": "image/png"}


@app.get("/top")
def top_weekly() -> tuple:
    uname = _channel_username()
    page = requests.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    jokes_html = ""
    total = 0
    if _settings is not None:
        db = Database(_settings.database_url or _settings.database_path)
        with db.connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) AS c FROM jokes WHERE published_at IS NOT NULL"
            ).fetchone()["c"]
            rows = conn.execute(
                "SELECT id, text, published_at FROM jokes WHERE published_at IS NOT NULL "
                "ORDER BY published_at DESC LIMIT ? OFFSET ?",
                (per_page, offset),
            ).fetchall()
        if rows:
            for i, row in enumerate(rows, 1):
                text = row["text"]
                joke_id = row["id"]
                display = text.replace("\n", " ")[:200].rstrip() + "\u2026" if len(text) > 200 else text
                short = text.replace("\n", " ")[:120].strip()
                share_tg = f"https://t.me/share/url?url={_BASE}/joke/{joke_id}&text={html_mod.quote(short)}"
                jokes_html += f"""<li>
          <a href="/joke/{joke_id}">{html_mod.escape(display)}</a>
          <br><small><a href="{share_tg}" target="_blank">\u2197 \u041F\u043E\u0434\u0435\u043B\u0438\u0442\u044C\u0441\u044F</a></small>
        </li>"""
    if not jokes_html:
        jokes_html = "<li>\u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C \u043D\u0430 @%s \u2014 \u0442\u0430\u043C \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C \u0441\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B!</li>" % uname
    total_pages = max(1, (total + per_page - 1) // per_page)
    pagi = f'<div class="pagi">\u0421\u0442\u0440\u0430\u043D\u0438\u0446\u0430 {page} \u0438\u0437 {total_pages}'
    if page > 1:
        pagi += f' &nbsp; <a href="/top?page={page-1}">\u2190 \u041F\u0440\u0435\u0434\u044B\u0434\u0443\u0449\u0430\u044F</a>'
    if page < total_pages:
        pagi += f' &nbsp; <a href="/top?page={page+1}">\u0421\u043B\u0435\u0434\u0443\u044E\u0449\u0430\u044F \u2192</a>'
    pagi += "</div>"

    page = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>\u041B\u0443\u0447\u0448\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B — @{uname}</title>
  <meta name="description" content="\u0421\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u0438\u0437 Telegram \u043A\u0430\u043D\u0430\u043B\u0430 @{uname}. \u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C!">
  <meta property="og:title" content="\u041B\u0443\u0447\u0448\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B — @{uname}">
  <meta property="og:description" content="\u0421\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C. \u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C \u043D\u0430 @{uname}!">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary">
  <meta name="robots" content="index,follow">
  <link rel="alternate" type="application/rss+xml" title="@{uname} RSS" href="{_BASE}/rss.xml">
  <style>{_STYLE}</style>
</head>
<body>
  <h1>\U0001F923 \u0410\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u0438\u0437 @{uname}</h1>
  <p>\u0421\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B, \u0431\u0438\u0442\u0432\u044B \u0438 \u043A\u043E\u043D\u043A\u0443\u0440\u0441\u044B \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C!</p>
  <ol>{jokes_html}</ol>
  {pagi}
  <div id="refLeaderboard" style="background:white;border-radius:12px;padding:16px;margin:16px 0;box-shadow:0 2px 8px rgba(0,0,0,0.08)">
    <h2 style="margin:0 0 10px;font-size:18px">\U0001F3C6 \u0422\u043E\u043F \u0440\u0435\u0444\u0435\u0440\u0430\u043B\u043E\u0432</h2>
    <div id="refList" style="font-size:14px;color:#666">\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430...</div>
    <p style="font-size:12px;color:#999;margin:8px 0 0">\u0427\u0442\u043E\u0431\u044B \u043F\u043E\u043F\u0430\u0441\u0442\u044C \u0432 \u0442\u043E\u043F, \u043F\u0438\u0448\u0438 \u0431\u043E\u0442\u0443 /invite</p>
  </div>
  <script>
    (function(){{
      var x = new XMLHttpRequest();
      x.open('GET', '{_BASE}/api/top-referrers', true);
      x.onload = function() {{
        if (x.status === 200) {{
          var data = JSON.parse(x.responseText);
          var html = '<ol style="margin:0;padding-left:20px">';
          for (var i = 0; i < data.length; i++) {{
            var name = data[i].name || 'ID ' + data[i].user_id;
            html += '<li><b>' + name + '</b> — ' + data[i].count + ' \u0434\u0440\u0443\u0437\u0435\u0439</li>';
          }}
          html += '</ol>';
          document.getElementById('refList').innerHTML = html;
        }}
      }};
      x.send();
    }})();
  </script>
  <a class="sub" href="https://t.me/{uname}">\U0001F514 \u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F \u043D\u0430 @{uname}</a>
  <p class="footer"><a href="/">\u041D\u0430 \u0433\u043B\u0430\u0432\u043D\u0443\u044E</a> \u2022 <a href="/search">\u041F\u043E\u0438\u0441\u043A</a> \u2022 <a href="/rss.xml">RSS</a> \u2022 <a href="/sitemap.xml">\u041A\u0430\u0440\u0442\u0430 \u0441\u0430\u0439\u0442\u0430</a></p>
</body>
</html>"""
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


_RUBRIC_SLUGS: dict[str, int] = {
    "semeynoe": 0,
    "rabochee": 1,
    "zhivotnye": 2,
    "armeyskoe": 3,
    "chernyy-yumor": 4,
    "zastolnoe": 5,
    "zhiznennoe": 6,
}


@app.get("/rubric/<slug>")
def rubric_page(slug: str) -> tuple:
    idx = _RUBRIC_SLUGS.get(slug)
    if idx is None:
        abort(404)
    rubric = RUBRICS[idx]
    uname = _channel_username()
    canonical = f"{_BASE}/rubric/{slug}"
    jokes_html = ""
    if _settings is not None:
        db = Database(_settings.database_url or _settings.database_path)
        jokes = db.get_published_by_keywords(rubric["keywords"], limit=30)
        if jokes:
            for joke in jokes:
                text = joke["text"]
                joke_id = joke.get("id", "")
                display = text.replace("\n", " ")[:200].rstrip() + "\u2026" if len(text) > 200 else text
                short = text.replace("\n", " ")[:120].strip()
                share_tg = f"https://t.me/share/url?url={_BASE}/joke/{joke_id}&text={html_mod.quote(short)}" if joke_id else ""
                link = f"/joke/{joke_id}" if joke_id else f"https://t.me/{uname}"
                jokes_html += f"""<li>
          <a href="{link}">{html_mod.escape(display)}</a>
          <br><small><a href="{share_tg}" target="_blank">\u2197 \u041F\u043E\u0434\u0435\u043B\u0438\u0442\u044C\u0441\u044F</a></small>
        </li>"""
    if not jokes_html:
        jokes_html = f"<li>\u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C \u043D\u0430 @{uname} \u2014 \u0442\u0430\u043C \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C \u0441\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B!</li>"
    rubric_emoji = rubric.get("emoji", "")
    rubric_name = rubric["name"]
    page = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>\u0410\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u043F\u0440\u043E {rubric_name.lower()} — @{uname}</title>
  <meta name="description" content="\u0421\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u043F\u0440\u043E {rubric_name.lower()}. \u041A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C \u043D\u043E\u0432\u044B\u0435 \u043F\u043E\u0441\u0442\u044B \u0432 Telegram @{uname}!">
  <meta property="og:title" content="{rubric_emoji} \u0410\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u043F\u0440\u043E {rubric_name.lower()}">
  <meta property="og:description" content="\u0421\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u043F\u0440\u043E {rubric_name.lower()} \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C. \u041F\u043E\u0434\u043F\u0438\u0448\u0438\u0441\u044C!">
  <meta property="og:url" content="{canonical}">
  <meta property="og:type" content="website">
  <meta name="twitter:card" content="summary">
  <meta name="robots" content="index,follow">
  <link rel="canonical" href="{canonical}">
  <style>{_STYLE}</style>
</head>
<body>
  <h1>{rubric_emoji} \u0410\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u043F\u0440\u043E {rubric_name.lower()}</h1>
  <p>\u0421\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u0438\u0437 Telegram \u043A\u0430\u043D\u0430\u043B\u0430 @{uname}.</p>
  <ol>{jokes_html}</ol>
  <a class="sub" href="https://t.me/{uname}">\U0001F514 \u041F\u043E\u0434\u043F\u0438\u0441\u0430\u0442\u044C\u0441\u044F \u043D\u0430 @{uname}</a>
  <p class="footer"><a href="/">\u041D\u0430 \u0433\u043B\u0430\u0432\u043D\u0443\u044E</a> \u2022 <a href="/search">\u041F\u043E\u0438\u0441\u043A</a> \u2022 <a href="/rss.xml">RSS</a></p>
</body>
</html>"""
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/rss.xml")
def rss_feed() -> tuple:
    uname = _channel_username()
    channel_url = f"https://t.me/{uname}"
    items = ""
    if _settings is not None:
        db = Database(_settings.database_url or _settings.database_path)
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT text, published_at FROM jokes WHERE published_at IS NOT NULL "
                "ORDER BY published_at DESC LIMIT 20"
            ).fetchall()
        for row in rows:
            title = row["text"].split("\n")[0][:100].rstrip() + "\u2026" if len(row["text"]) > 100 else row["text"]
            desc = html_mod.escape(row["text"].replace("\n", "<br>"))
            pub_date = row["published_at"]
            items += f"""    <item>
      <title>{html_mod.escape(title)}</title>
      <link>{channel_url}</link>
      <description><![CDATA[{desc}]]></description>
      <pubDate>{pub_date}</pubDate>
      <guid isPermaLink="false">{row["published_at"]}</guid>
    </item>"""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>\u0410\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u0438\u0437 @{uname}</title>
    <link>{channel_url}</link>
    <description>\u0421\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u043A\u0430\u0436\u0434\u044B\u0439 \u0434\u0435\u043D\u044C \u0432 Telegram</description>
    <language>ru</language>
    <atom:link href="{_BASE}/rss.xml" rel="self" type="application/rss+xml"/>
{items}  </channel>
</rss>"""
    return xml, 200, {"Content-Type": "application/rss+xml; charset=utf-8"}


@app.get("/sitemap.xml")
def sitemap_index() -> tuple:
    base = _BASE
    sitemaps = [
        f"  <sitemap><loc>{base}/sitemap-pages.xml</loc></sitemap>",
        f"  <sitemap><loc>{base}/sitemap-jokes.xml</loc></sitemap>",
    ]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(sitemaps)}
</sitemapindex>"""
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


@app.get("/sitemap-pages.xml")
def sitemap_pages() -> tuple:
    base = _BASE
    urls = [
        f"  <url><loc>{base}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>",
        f"  <url><loc>{base}/top</loc><changefreq>daily</changefreq><priority>0.8</priority></url>",
        f"  <url><loc>{base}/random</loc><changefreq>daily</changefreq><priority>0.5</priority></url>",
    ]
    for slug in _RUBRIC_SLUGS:
        urls.append(f"  <url><loc>{base}/rubric/{slug}</loc><changefreq>daily</changefreq><priority>0.7</priority></url>")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


@app.get("/sitemap-jokes.xml")
def sitemap_jokes() -> tuple:
    base = _BASE
    urls = []
    if _settings is not None:
        db = Database(_settings.database_url or _settings.database_path)
        with db.connect() as conn:
            all_ids = conn.execute(
                "SELECT id FROM jokes WHERE published_at IS NOT NULL ORDER BY published_at DESC"
            ).fetchall()
        for row in all_ids:
            urls.append(f"  <url><loc>{base}/joke/{row['id']}</loc><changefreq>monthly</changefreq><priority>0.5</priority></url>")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


@app.get("/widget")
def widget_info() -> tuple:
    uname = _channel_username()
    embed = f'<script src="{_BASE}/widget.js"></script>'
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>\u0412\u0438\u0434\u0436\u0435\u0442 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u0430 — @{uname}</title>
  <meta name="robots" content="noindex,follow">
  <style>{_STYLE}</style>
</head>
<body>
  <h1>\U0001F4D1 \u0412\u0438\u0434\u0436\u0435\u0442 \u00AB\u0428\u0443\u0442\u043A\u0430 \u0434\u043D\u044F\u00BB</h1>
  <p>\u0412\u0441\u0442\u0430\u0432\u044C\u0442\u0435 \u044D\u0442\u043E\u0442 \u043A\u043E\u0434 \u043D\u0430 \u0441\u0432\u043E\u0439 \u0441\u0430\u0439\u0442 \u0438 \u043F\u043E\u043A\u0430\u0437\u044B\u0432\u0430\u0439\u0442\u0435 \u0441\u0432\u0435\u0436\u0438\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u044B \u0432\u0430\u0448\u0438\u043C \u043F\u043E\u0441\u0435\u0442\u0438\u0442\u0435\u043B\u044F\u043C!</p>
  <div style="background:white;border-radius:12px;padding:20px;margin:16px 0;box-shadow:0 2px 8px rgba(0,0,0,0.08)">
    <code style="word-break:break-all;font-size:13px">{html_mod.escape(embed)}</code>
  </div>
  <p>\u041F\u0440\u0435\u0434\u043F\u0440\u043E\u0441\u043C\u043E\u0442\u0440:</p>
  {embed}
  <p class="footer"><a href="/">\u041D\u0430 \u0433\u043B\u0430\u0432\u043D\u0443\u044E</a> \u2022 <a href="https://t.me/{uname}">@{uname}</a></p>
</body>
</html>"""
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/search")
def search() -> tuple:
    q = requests.args.get("q", "").strip()
    uname = _channel_username()
    results_html = ""
    if q and _settings is not None:
        db = Database(_settings.database_url or _settings.database_path)
        with db.connect() as conn:
            like = f"%{q}%"
            rows = conn.execute(
                "SELECT text, published_at FROM jokes WHERE published_at IS NOT NULL AND text LIKE ? "
                "ORDER BY published_at DESC LIMIT 30",
                (like,),
            ).fetchall()
        for row in rows:
            text = row["text"]
            needle = html_mod.escape(q)
            display = html_mod.escape(text[:300])
            display = display.replace(needle, f"<mark>{needle}</mark>")
            results_html += f"<li>{display}</li>"
    title = f"\u041F\u043E\u0438\u0441\u043A: {html_mod.escape(q)} — @{uname}" if q else f"\u041F\u043E\u0438\u0441\u043A \u043F\u043E \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u0430\u043C — @{uname}"
    desc = f"\u0420\u0435\u0437\u0443\u043B\u044C\u0442\u0430\u0442\u044B \u043F\u043E\u0438\u0441\u043A\u0430 \u043F\u043E \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u0430\u043C: {html_mod.escape(q)}" if q else "\u041F\u043E\u0438\u0441\u043A \u043F\u043E \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u0430\u043C \u0438\u0437 Telegram \u043A\u0430\u043D\u0430\u043B\u0430"
    if not results_html:
        results_html = f"<li>\u041D\u0438\u0447\u0435\u0433\u043E \u043D\u0435 \u043D\u0430\u0439\u0434\u0435\u043D\u043E \u043F\u043E \u0437\u0430\u043F\u0440\u043E\u0441\u0443 \xAB{html_mod.escape(q)}\xBB</li>" if q else "<li>\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043F\u043E\u0438\u0441\u043A\u043E\u0432\u044B\u0439 \u0437\u0430\u043F\u0440\u043E\u0441 \u0432\u044B\u0448\u0435</li>"
    page = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="robots" content="noindex,follow">
  <title>{title}</title>
  <meta name="description" content="{desc[:200]}">
  <style>{_STYLE}</style>
  <style>mark {{ background: #ffd54f; padding: 0 2px; }}</style>
</head>
<body>
  <h1>\U0001F50D \u041F\u043E\u0438\u0441\u043A \u043F\u043E \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u0430\u043C</h1>
  <form action="/search" method="get" style="margin:16px 0">
    <input type="text" name="q" value="{html_mod.escape(q)}" placeholder="\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043A\u043B\u044E\u0447\u0435\u0432\u043E\u0435 \u0441\u043B\u043E\u0432\u043E..." style="padding:10px;font-size:16px;width:70%;border:2px solid #0088cc;border-radius:8px">
    <button type="submit" style="padding:10px 20px;font-size:16px;background:#0088cc;color:white;border:none;border-radius:8px;cursor:pointer">\u041D\u0430\u0439\u0442\u0438</button>
  </form>
  <ol>{results_html}</ol>
  <p class="footer"><a href="/">\u041D\u0430 \u0433\u043B\u0430\u0432\u043D\u0443\u044E</a> \u2022 <a href="https://t.me/{uname}">\u041A\u0430\u043D\u0430\u043B Telegram</a></p>
</body>
</html>"""
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


@app.get("/random")
def random_joke() -> tuple:
    ensure_bot_started()
    if _settings is None:
        return redirect("/"), 302
    db = Database(_settings.database_url or _settings.database_path)
    msg_id = db.get_random_published_msg_id()
    if msg_id:
        return redirect(f"/p/{msg_id}"), 302
    return redirect("/top"), 302


@app.get("/api/top-referrers")
def api_top_referrers() -> tuple:
    ensure_bot_started()
    if _settings is None:
        return jsonify([]), 503
    db = Database(_settings.database_url or _settings.database_path)
    top = db.get_top_referrers(limit=10)
    return jsonify(top), 200, {"Access-Control-Allow-Origin": "*", "Cache-Control": "public, max-age=300"}


@app.get("/api/random-joke")
def api_random_joke() -> tuple:
    ensure_bot_started()
    if _settings is None:
        return jsonify({"error": "not ready"}), 503
    db = Database(_settings.database_url or _settings.database_path)
    with db.connect() as conn:
        row = conn.execute(
            "SELECT id, text, published_at FROM jokes WHERE published_at IS NOT NULL ORDER BY RANDOM() LIMIT 1"
        ).fetchone()
    if not row:
        return jsonify({"error": "no jokes"}), 404
    uname = _channel_username()
    return jsonify({
        "id": row["id"],
        "text": row["text"],
        "url": f"{_BASE}/joke/{row['id']}",
        "channel": f"https://t.me/{uname}",
    }), 200, {"Access-Control-Allow-Origin": "*"}


@app.get("/widget.js")
def widget_js() -> tuple:
    base = _BASE
    js = f"""(function() {{
  var s = document.createElement('div');
  s.id = 'anetdodik-widget';
  s.innerHTML = '<div style="font-family:sans-serif;max-width:400px;margin:10px auto;border:2px solid #0088cc;border-radius:12px;padding:16px;background:#fff">'
    + '<div id="anetdodik-joke" style="font-size:15px;line-height:1.5;min-height:40px;color:#333">\u0417\u0430\u0433\u0440\u0443\u0437\u043A\u0430...</div>'
    + '<div style="margin-top:10px;text-align:center">'
    + '<a href="https://t.me/Anetdodik" target="_blank" style="display:inline-block;padding:8px 16px;background:#0088cc;color:#fff;border-radius:6px;text-decoration:none;font-size:14px">\U0001F514 \u0411\u043E\u043B\u044C\u0448\u0435 \u0430\u043D\u0435\u043A\u0434\u043E\u0442\u043E\u0432</a>'
    + '</div></div>';
  document.currentScript.parentNode.insertBefore(s, document.currentScript);
  var x = new XMLHttpRequest();
  x.open('GET', '{base}/api/random-joke', true);
  x.onload = function() {{ if (x.status === 200) {{ var d = JSON.parse(x.responseText); document.getElementById('anetdodik-joke').innerHTML = d.text.replace(/\\n/g, '<br>'); }} }};
  x.send();
}})();"""
    return js, 200, {"Content-Type": "application/javascript; charset=utf-8"}


@app.get("/robots.txt")
def robots() -> tuple:
    txt = f"""User-agent: *
Allow: /
Sitemap: {_BASE}/sitemap.xml
"""
    return txt, 200, {"Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    ensure_bot_started()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
