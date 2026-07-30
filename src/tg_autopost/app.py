import argparse
import logging
import sys

from .config import load_settings
from .database import Database
from .handlers import PollingHandler


def configure_logging() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def build_services():
    from .ingest import JokeIngestor
    from .publisher import TelegramPublisher
    from .sources.anekdot_ru import AnekdotRuSource
    from .sources.anekdotov_net import AnekdotovNetSource
    from .sources.baneks_ru import BaneksRuSource
    from .sources.it_jokes import ItJokesSource
    from .sources.reddit_jokes import RedditJokesSource

    settings = load_settings()
    db = Database(settings.database_url or settings.database_path)
    sources: list = [
        AnekdotRuSource(timeout=settings.http_timeout),
        AnekdotovNetSource(timeout=settings.http_timeout),
        BaneksRuSource(timeout=settings.http_timeout),
        ItJokesSource(),
        RedditJokesSource(),
    ]
    if settings.telegram_sources:
        if settings.telethon_api_id and settings.telethon_api_hash and settings.telethon_session_string:
            try:
                from .sources.telethon_channel import TelethonChannelSource
                sources.append(TelethonChannelSource(
                    api_id=settings.telethon_api_id,
                    api_hash=settings.telethon_api_hash,
                    session_string=settings.telethon_session_string,
                    channels=list(settings.telegram_sources),
                    timeout=settings.http_timeout,
                ))
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Failed to init Telethon source")
        else:
            from .sources.telegram_channel import TelegramChannelSource
            sources.append(TelegramChannelSource(list(settings.telegram_sources), timeout=settings.http_timeout))
    ingestor = JokeIngestor(db, sources)
    publisher = TelegramPublisher(settings, db)
    return settings, db, ingestor, publisher


def run_ingest() -> int:
    settings, _, ingestor, _ = build_services()
    inserted = ingestor.run(settings.fetch_limit)
    logging.getLogger(__name__).info("Inserted %s new jokes", inserted)
    return inserted


def run_publish() -> bool:
    _, _, _, publisher = build_services()
    return publisher.publish_next()


def publish_horoscope() -> bool:
    _, _, _, publisher = build_services()
    publisher._send_horoscope()
    return True


def publish_anti_advice() -> bool:
    _, _, _, publisher = build_services()
    publisher._send_anti_advice()
    return True


def publish_meme_image() -> bool:
    _, _, _, publisher = build_services()
    return publisher._publish_meme()


def pin_best() -> None:
    _, _, _, publisher = build_services()
    publisher._pin_best_post()


def publish_challenge() -> None:
    _, _, _, publisher = build_services()
    publisher._send_challenge()


def publish_newsjacker() -> bool:
    from .newsjacker import make_newsjacker_post

    settings, _, _, publisher = build_services()
    result = make_newsjacker_post(publisher.db)
    if not result:
        logger = logging.getLogger(__name__)
        logger.info("No newsjacker post, falling back to regular publish")
        return run_publish()
    post, content_hash = result
    ok = publisher.send_newsjacker(post)
    if ok:
        publisher.db.mark_published(content_hash)
    return ok


def run_ingest_and_publish() -> None:
    run_ingest()
    run_publish()


def run_scheduler() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from datetime import datetime, timezone

    scheduler = BlockingScheduler(timezone="Europe/Moscow")

    # reduced schedule — 5 posts/day MSK
    scheduler.add_job(run_ingest_and_publish, "cron", hour=10, minute=0)      # Regular joke
    scheduler.add_job(publish_horoscope, "cron", hour=11, minute=30)          # Horoscope
    scheduler.add_job(run_ingest_and_publish, "cron", hour=14, minute=0)      # Regular joke
    scheduler.add_job(publish_meme_image, "cron", hour=17, minute=0)          # Meme
    scheduler.add_job(publish_newsjacker, "cron", hour=20, minute=0)          # Newsjacker (fallback: regular joke)
    scheduler.add_job(pin_best, "cron", hour=23, minute=0)                    # Pin best

    # Run initial ingest as non-blocking background job so scheduler starts immediately
    def _startup_ingest():
        try:
            run_ingest()
            db = Database(load_settings().database_url or load_settings().database_path)
            marked = db.mark_source_published("meme_api")
            if marked:
                logging.getLogger(__name__).info("Marked %s existing meme_api jokes as published (disabled source)", marked)
            remaining = db.count_unpublished()
            logging.getLogger(__name__).info("Unpublished jokes remaining: %s", remaining)
        except Exception:
            logging.getLogger(__name__).exception("Startup ingest failed, scheduler will still start")

    scheduler.add_job(_startup_ingest, "date", run_date=datetime.now(timezone.utc))

    logger = logging.getLogger(__name__)
    logger.info(
        "Scheduler started — 5 posts/day: 2 jokes + horoscope + meme + newsjacker + pin",
    )

    scheduler.start()


def run_bot() -> None:
    settings = load_settings()
    db = Database(settings.database_url or settings.database_path)
    handler = PollingHandler(settings, db)
    handler.run_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram joke autoposting service")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "ingest", "publish", "bot", "horoscope", "antiadvice", "meme"])
    args = parser.parse_args()

    configure_logging()

    if args.command == "ingest":
        run_ingest()
    elif args.command == "publish":
        run_publish()
    elif args.command == "horoscope":
        publish_horoscope()
    elif args.command == "antiadvice":
        publish_anti_advice()
    elif args.command == "meme":
        publish_meme_image()
    elif args.command == "bot":
        run_bot()
    else:
        run_scheduler()

    return 0
