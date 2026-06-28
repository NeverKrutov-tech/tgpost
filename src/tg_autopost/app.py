import argparse
import logging
import sys
import threading

from apscheduler.schedulers.blocking import BlockingScheduler

from .config import load_settings
from .database import Database
from .handlers import PollingHandler
from .ingest import JokeIngestor
from .publisher import TelegramPublisher
from .sources.anekdot_ru import AnekdotRuSource
from .sources.anekdotov_net import AnekdotovNetSource
from .sources.telegram_channel import TelegramChannelSource


def configure_logging() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def build_services() -> tuple[object, Database, JokeIngestor, TelegramPublisher]:
    settings = load_settings()
    db = Database(settings.database_path)
    sources: list = [
        AnekdotRuSource(timeout=settings.http_timeout),
        AnekdotovNetSource(timeout=settings.http_timeout),
    ]
    if settings.telegram_sources:
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


def run_ingest_and_publish() -> None:
    run_ingest()
    run_publish()


def run_scheduler() -> None:
    settings = load_settings()
    db = Database(settings.database_path)

    handler = PollingHandler(settings, db)
    polling_thread = threading.Thread(target=handler.run_forever, daemon=True)
    polling_thread.start()

    scheduler = BlockingScheduler()

    for hour in range(6, 24, settings.post_interval_hours):
        scheduler.add_job(run_ingest_and_publish, "cron", hour=hour, minute=0, jitter=900)

    logging.getLogger(__name__).info(
        "Scheduler started — posts at %s:00, every %s hours (night pause 23:00–07:59)",
        "8", settings.post_interval_hours,
    )

    run_ingest_and_publish()
    scheduler.start()


def main() -> int:
    parser = argparse.ArgumentParser(description="Telegram joke autoposting service")
    parser.add_argument("command", nargs="?", default="run", choices=["run", "ingest", "publish"])
    args = parser.parse_args()

    configure_logging()

    if args.command == "ingest":
        run_ingest()
    elif args.command == "publish":
        run_publish()
    else:
        run_scheduler()

    return 0
