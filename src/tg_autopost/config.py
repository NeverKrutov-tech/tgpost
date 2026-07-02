from dataclasses import dataclass
import os
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    channel_id: str
    admin_id: int | None = None
    channel_link: str = ""
    telegram_sources: tuple[str, ...] = ()
    post_interval_hours: int = 2
    fetch_limit: int = 30
    database_path: str = "data/jokes.db"
    http_timeout: int = 20
    youtube_api_key: str = ""
    youtube_channel_id: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    hf_token: str = ""
    cf_account_id: str = ""
    cf_api_token: str = ""


def load_settings() -> Settings:
    load_dotenv()
    bot_token = os.getenv("BOT_TOKEN", "").strip()
    channel_id = os.getenv("CHANNEL_ID", "").strip()

    if not bot_token:
        raise ValueError("BOT_TOKEN is not set")
    if not channel_id:
        raise ValueError("CHANNEL_ID is not set")

    raw_admin = os.getenv("ADMIN_ID", "").strip()
    admin_id = int(raw_admin) if raw_admin else None

    raw_tg_sources = os.getenv("TELEGRAM_SOURCES", "").strip()
    telegram_sources = tuple(ch.strip() for ch in raw_tg_sources.split(",") if ch.strip())

    return Settings(
        bot_token=bot_token,
        channel_id=channel_id,
        admin_id=admin_id,
        channel_link=os.getenv("CHANNEL_LINK", "").strip(),
        telegram_sources=telegram_sources,
        post_interval_hours=int(os.getenv("POST_INTERVAL_HOURS", "2")),
        fetch_limit=int(os.getenv("FETCH_LIMIT", "30")),
        database_path=os.getenv("DATABASE_PATH", "data/jokes.db"),
        http_timeout=int(os.getenv("HTTP_TIMEOUT", "20")),
        youtube_api_key=os.getenv("YOUTUBE_API_KEY", "").strip(),
        youtube_channel_id=os.getenv("YOUTUBE_CHANNEL_ID", "").strip(),
        youtube_client_id=os.getenv("YOUTUBE_CLIENT_ID", "").strip(),
        youtube_client_secret=os.getenv("YOUTUBE_CLIENT_SECRET", "").strip(),
        youtube_refresh_token=os.getenv("YOUTUBE_REFRESH_TOKEN", "").strip(),
        hf_token=os.getenv("HF_TOKEN", "").strip(),
        cf_account_id=os.getenv("CF_ACCOUNT_ID", "").strip(),
        cf_api_token=os.getenv("CF_API_TOKEN", "").strip(),
    )
