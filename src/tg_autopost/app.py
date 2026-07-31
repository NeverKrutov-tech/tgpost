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
    logger = logging.getLogger(__name__)
    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError
        settings, _, ingestor, _ = build_services()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ingestor.run, settings.fetch_limit)
            inserted = future.result(timeout=120)
            logger.info("Inserted %s new jokes", inserted)
            return inserted
    except TimeoutError:
        logger.warning("Ingest timed out after 120s")
        return 0
    except Exception:
        logger.exception("Ingest failed")
        return 0


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


def _run_with_lock(action: str, func, ttl_seconds: int = 3600) -> bool:
    """Run a cron action with idempotency lock. Returns True if executed, False if skipped."""
    from .config import load_settings
    from .database import Database

    settings = load_settings()
    db = Database(settings.database_url or settings.database_path)
    if not db.try_acquire_cron_lock(action, ttl_seconds):
        logging.getLogger(__name__).info("Cron %s skipped (lock held)", action)
        return False
    try:
        result = func()
        logging.getLogger(__name__).info("Cron %s executed", action)
        return True
    except Exception:
        logging.getLogger(__name__).exception("Cron %s failed", action)
        return False


def run_catchup() -> None:
    """Run catch-up for any missed scheduled slots."""
    from datetime import datetime, timezone, timedelta
    from .config import load_settings
    from .database import Database

    settings = load_settings()
    db = Database(settings.database_url or settings.database_path)
    now = datetime.now(timezone.utc)

    # Schedule: (action_name, hour, minute, function, ttl_seconds)
    schedule = [
        ("joke_10", 10, 0, lambda: _run_with_lock("joke_10", run_ingest_and_publish), 7200),
        ("horoscope", 11, 30, lambda: _run_with_lock("horoscope", publish_horoscope), 7200),
        ("joke_14", 14, 0, lambda: _run_with_lock("joke_14", run_ingest_and_publish), 7200),
        ("meme", 17, 0, lambda: _run_with_lock("meme", publish_meme_image), 7200),
        ("newsjacker", 20, 0, lambda: _run_with_lock("newsjacker", publish_newsjacker), 7200),
        ("pin", 23, 0, lambda: _run_with_lock("pin", pin_best), 7200),
    ]

    for action, hour, minute, func, ttl in schedule:
        # Calculate when this slot should have run today
        slot_time = datetime(now.year, now.month, now.day, hour, minute, tzinfo=timezone.utc)
        # If slot is in the past (more than 10 min ago) and lock not set, run it
        if slot_time < now - timedelta(minutes=10):
            lock_time = db.get_cron_lock_time(action)
            if lock_time is None:
                # No lock set, run catch-up
                logging.getLogger(__name__).info("Catch-up: running missed %s", action)
                func()
            elif now.timestamp() - lock_time > ttl:
                # Lock expired, run catch-up
                logging.getLogger(__name__).info("Catch-up: lock expired for %s", action)
                func()


def run_scheduler() -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from datetime import datetime, timezone

    scheduler = BlockingScheduler(timezone="Europe/Moscow")

    # NO cron jobs here — external cron (cron-job.org) handles scheduling via HTTP endpoints
    # This scheduler only runs startup ingest and keeps the process alive

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
            # Run catch-up after startup
            run_catchup()
        except Exception:
            logging.getLogger(__name__).exception("Startup ingest failed, scheduler will still start")

    scheduler.add_job(_startup_ingest, "date", run_date=datetime.now(timezone.utc))

    logger = logging.getLogger(__name__)
    logger.info("Scheduler started — external cron handles 5 posts/day via HTTP endpoints")

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
