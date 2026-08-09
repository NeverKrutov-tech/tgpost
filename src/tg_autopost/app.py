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

    settings = load_settings()
    db = Database(settings.database_url or settings.database_path)
    sources: list = []
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
    # The former meme source is disabled. Keep the 17:00 slot productive by
    # falling back to a regular joke instead of returning 200 without a post.
    if publisher._publish_meme():
        return True
    logging.getLogger(__name__).info("No meme available, falling back to regular publish")
    return run_publish()


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


def run_ingest_and_publish() -> bool:
    run_ingest()
    return run_publish()


def _run_with_lock(action: str, func, ttl_seconds: int = 3600) -> bool:
    """Run a cron action with idempotency lock.

    Returns True only if the slot actually posted something. False covers
    three cases that used to look identical from outside: lock already held,
    the action ran but had nothing to publish (empty queue), and a crash.
    Callers that report status back to cron (e.g. /cron/joke) rely on this
    to tell "silently did nothing" apart from "worked".
    """
    from .config import load_settings
    from .database import Database

    settings = load_settings()
    db = Database(settings.database_url or settings.database_path)
    if not db.try_acquire_cron_lock(action, ttl_seconds):
        logging.getLogger(__name__).info("Cron %s skipped (lock held)", action)
        return False
    try:
        result = func()
        posted = result is not False
        logging.getLogger(__name__).info("Cron %s executed (posted=%s)", action, posted)
        return posted
    except Exception:
        logging.getLogger(__name__).exception("Cron %s failed", action)
        return False


def run_catchup() -> None:
    """Run catch-up for any missed scheduled slots."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from .config import load_settings
    from .database import Database

    settings = load_settings()
    db = Database(settings.database_url or settings.database_path)
    msk = ZoneInfo("Europe/Moscow")
    now = datetime.now(msk)
    today = now.date()

    # Schedule in MSK: (action_name, hour, minute, function)
    schedule = [
        ("joke_10", 10, 0, lambda: _run_with_lock("joke_10", run_ingest_and_publish)),
        ("horoscope", 11, 30, lambda: _run_with_lock("horoscope", publish_horoscope)),
        ("joke_14", 14, 0, lambda: _run_with_lock("joke_14", run_ingest_and_publish)),
        ("meme", 17, 0, lambda: _run_with_lock("meme", publish_meme_image)),
        ("newsjacker", 20, 0, lambda: _run_with_lock("newsjacker", publish_newsjacker)),
        ("pin", 23, 0, lambda: _run_with_lock("pin", pin_best)),
    ]

    for action, hour, minute, func in schedule:
        # Slot today in MSK
        slot_time = datetime(now.year, now.month, now.day, hour, minute, tzinfo=msk)
        # Only catch up if the slot is more than 10 min in the past
        if slot_time > now - timedelta(minutes=10):
            continue
        lock_time = db.get_cron_lock_time(action)
        if lock_time is None:
            logging.getLogger(__name__).info("Catch-up: running missed %s", action)
            func()
        else:
            # Compare by calendar day (MSK), not by TTL, to avoid double-posting
            # a slot that already ran today.
            lock_date = datetime.fromtimestamp(lock_time, tz=msk).date()
            if lock_date < today:
                logging.getLogger(__name__).info("Catch-up: running missed %s (last run %s)", action, lock_date)
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
            # NOTE: no automatic catch-up on startup. On Render free tier the
            # SQLite DB is ephemeral and wiped on every deploy/restart, so locks
            # are lost and catch-up would blindly re-publish slots that already
            # went out (double posts). External cron is the source of truth.
            # Use GET /cron/catchup?key=... manually when a slot was genuinely missed.
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
