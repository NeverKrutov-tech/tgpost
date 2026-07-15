import html
from pathlib import Path
from urllib.parse import quote

from flask import Blueprint

from .config import load_settings
from .database import Database


growth_pages = Blueprint("growth_pages", __name__)
BASE_URL = "https://tgpost-bot-l4wq.onrender.com"


def _channel_username() -> str:
    return "Anetdodik"


@growth_pages.get("/mini")
def mini_app() -> tuple:
    """Serve the Telegram Mini App from its standalone HTML template."""
    path = Path(__file__).with_name("miniapp.html")
    if not path.exists():
        return "Mini App is unavailable", 503
    return path.read_text(encoding="utf-8"), 200, {"Content-Type": "text/html; charset=utf-8"}


@growth_pages.get("/weekly-best")
def weekly_best() -> tuple:
    """SEO and shareable compilation of ten recently published jokes."""
    from .config import load_settings

    uname = _channel_username()
    channel_url = f"https://t.me/{uname}"
    rows = []
    if _settings is not None:
        db = Database(_settings.database_url or _settings.database_path)
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT id, text, telegram_msg_id FROM jokes "
                "WHERE published_at IS NOT NULL ORDER BY published_at DESC LIMIT 10"
            ).fetchall()

    cards = ""
    for position, row in enumerate(rows, 1):
        text = row["text"]
        preview = text.replace("\n", " ")[:260].strip()
        if len(text) > 260:
            preview += "..."
        joke_url = f"{BASE_URL}/joke/{row['id']}"
        share_url = f"https://t.me/share/url?url={quote(joke_url)}&text={quote(preview)}"
        telegram_url = f"https://t.me/{uname}/{row['telegram_msg_id']}" if row["telegram_msg_id"] else joke_url
        cards += f"""
        <article class="card">
          <span class="rank">#{position}</span>
          <p>{html.escape(preview)}</p>
          <div><a href="{telegram_url}" target="_blank">Открыть в Telegram</a><a href="{share_url}" target="_blank">Поделиться</a></div>
        </article>"""

    if not cards:
        cards = "<p class='empty'>Подборка формируется. Новые анекдоты уже выходят в канале.</p>"

    page = f"""<!DOCTYPE html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Лучшие анекдоты недели — @{uname}</title>
<meta name="description" content="Еженедельная подборка лучших анекдотов. Подписывайся на @{uname}, чтобы не пропустить новые выпуски.">
<meta property="og:title" content="Лучшие анекдоты недели — @{uname}">
<meta property="og:description" content="Топ смешных анекдотов за неделю.">
<meta property="og:url" content="{BASE_URL}/weekly-best"><meta name="robots" content="index,follow">
<link rel="canonical" href="{BASE_URL}/weekly-best">
<style>
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#f4f6f8;color:#202124;margin:0;padding:24px;line-height:1.55}}main{{max-width:760px;margin:auto}}h1{{font-size:28px;margin:0 0 8px}}.intro{{color:#5f6368;margin:0 0 24px}}.card{{background:#fff;border-radius:12px;padding:20px 20px 16px;margin:12px 0;box-shadow:0 2px 10px #00000012}}.card p{{margin:0 0 14px;white-space:pre-wrap}}.rank{{display:inline-block;color:#0088cc;font-weight:700;font-size:13px;margin-bottom:8px}}.card a{{color:#0088cc;text-decoration:none;font-size:14px;font-weight:600;margin-right:18px}}.subscribe{{display:block;text-align:center;background:#0088cc;color:#fff!important;border-radius:10px;padding:14px;text-decoration:none;font-weight:700;margin:28px 0 10px}}.footer{{text-align:center;color:#777;font-size:14px}}.footer a{{color:#0088cc;text-decoration:none}}.empty{{background:#fff;padding:30px;border-radius:12px;text-align:center;color:#666}}
</style></head><body><main>
<h1>Лучшие анекдоты недели</h1>
<p class="intro">Свежая подборка из канала @{uname}. Отправь другу тот, который понравился больше всего.</p>
{cards}
<a class="subscribe" href="{channel_url}">Подписаться на @{uname}</a>
<p class="footer"><a href="/">Главная</a> · <a href="/top">Все анекдоты</a> · <a href="/mini">Мини-приложение</a> · <a href="/rss.xml">RSS</a></p>
</main></body></html>"""
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


@growth_pages.post("/api/miniapp/read")
def record_joke_read() -> tuple:
    """Record a joke read from Mini App and return updated streak."""
    from flask import request, jsonify
    settings = load_settings()
    if settings is None:
        return jsonify({"error": "not ready"}), 503
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if not user_id or not isinstance(user_id, int):
        return jsonify({"error": "user_id required"}), 400
    db = Database(settings.database_url or settings.database_path)
    current, longest = db.update_streak(user_id)
    db.record_joke_read(user_id)
    new_achievements = db.check_and_award_achievements(user_id)
    return jsonify({
        "streak": current,
        "longest_streak": longest,
        "new_achievements": new_achievements,
    })


@growth_pages.get("/api/miniapp/stats/<int:user_id>")
def get_user_stats(user_id: int) -> tuple:
    """Get user stats for Mini App."""
    from flask import jsonify
    settings = load_settings()
    if settings is None:
        return jsonify({"error": "not ready"}), 503
    db = Database(settings.database_url or settings.database_path)
    stats = db.get_user_stats(user_id)
    streak_current, streak_longest = db.get_streak(user_id)
    achievements = db.get_user_achievements(user_id)
    return jsonify({
        "stats": stats,
        "streak": {"current": streak_current, "longest": streak_longest},
        "achievements": achievements,
    })


@growth_pages.post("/api/viral/share-unlock")
def viral_share_unlock() -> tuple:
    """
    Track a share and unlock content for the user.
    Expected JSON: {user_id, content_id, share_platform}
    """
    from flask import request, jsonify
    settings = load_settings()
    if settings is None:
        return jsonify({"error": "not ready"}), 503
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    content_id = data.get("content_id")
    platform = data.get("platform", "unknown")
    if not user_id or not content_id:
        return jsonify({"error": "user_id and content_id required"}), 400

    db = Database(settings.database_url or settings.database_path)
    # Record the share
    db.record_share(user_id)
    # Check if user has shared enough to unlock (e.g., 3 shares per unlock)
    stats = db.get_user_stats(user_id)
    shares = stats.get("shares_count", 0)
    # Simple unlock logic: every 3 shares unlocks 1 premium content
    unlocked = shares >= 3 and (shares // 3) > (shares - 1) // 3
    # Award viral achievement
    new_achievements = db.check_and_award_achievements(user_id)
    return jsonify({
        "unlocked": unlocked,
        "shares_total": shares,
        "next_unlock_at": ((shares // 3) + 1) * 3,
        "new_achievements": new_achievements,
    })


@growth_pages.post("/api/viral/challenge")
def viral_challenge() -> tuple:
    """Create or accept a friend challenge."""
    from flask import request, jsonify
    settings = load_settings()
    if settings is None:
        return jsonify({"error": "not ready"}), 503
    data = request.get_json(silent=True) or {}
    action = data.get("action")  # "create" or "accept"
    user_id = data.get("user_id")
    challenge_type = data.get("type", "read_count")  # "read_count", "streak", "shares"
    target_user_id = data.get("target_user_id")  # for accept
    if not user_id:
        return jsonify({"error": "user_id required"}), 400
    
    db = Database(settings.database_url or settings.database_path)
    if action == "create":
        # Create a new challenge
        import uuid
        challenge_id = str(uuid.uuid4())[:8]
        with db.connect() as conn:
            conn.execute(
                """INSERT INTO viral_challenges (id, challenger_id, type, created_at)
                VALUES (?, ?, ?, ?)""",
                (challenge_id, user_id, challenge_type, datetime.now(timezone.utc).isoformat()),
            )
        return jsonify({"challenge_id": challenge_id, "type": challenge_type})
    
    elif action == "accept":
        if not target_user_id:
            return jsonify({"error": "target_user_id required"}), 400
        # Check if challenge exists and is pending
        with db.connect() as conn:
            row = conn.execute(
                "SELECT id, challenger_id, type, status FROM viral_challenges WHERE id = ? AND challenger_id = ? AND status = 'pending'",
                (target_user_id, user_id),
            ).fetchone()
            if not row:
                return jsonify({"error": "Challenge not found or already accepted"}), 404
            conn.execute(
                "UPDATE viral_challenges SET status = 'accepted', accepted_at = ? WHERE id = ?",
                (datetime.now(timezone.utc).isoformat(), target_user_id),
            )
        return jsonify({"success": True, "challenge_id": target_user_id})
    
    return jsonify({"error": "invalid action"}), 400


@growth_pages.get("/api/social-proof/subscriber-count")
def get_subscriber_count() -> tuple:
    """Get live subscriber count for social proof widgets."""
    from flask import jsonify
    settings = load_settings()
    if settings is None:
        return jsonify({"error": "not ready"}), 503
    db = Database(settings.database_url or settings.database_path)
    with db.connect() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM bot_subscribers").fetchone()
        count = row["c"] if row else 0
    return jsonify({"subscribers": count, "label": "Подписчиков"})


@growth_pages.get("/api/social-proof/recent-joins")
def get_recent_joins() -> tuple:
    """Get recent joins for social proof (last 50)."""
    from flask import jsonify
    settings = load_settings()
    if settings is None:
        return jsonify({"error": "not ready"}), 503
    db = Database(settings.database_url or settings.database_path)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT username, subscribed_at FROM bot_subscribers "
            "ORDER BY subscribed_at DESC LIMIT 50"
        ).fetchall()
    joins = [
        {
            "username": r["username"],
            "joined": r["subscribed_at"][:16].replace("T", " "),
        }
        for r in rows
    ]
    return jsonify({"recent": joins})
