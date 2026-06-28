import logging
from typing import Iterable

from .database import Database
from .models import Joke
from .sources.base import JokeSource

logger = logging.getLogger(__name__)


class JokeIngestor:
    def __init__(self, db: Database, sources: Iterable[JokeSource]) -> None:
        self.db = db
        self.sources = list(sources)

    def run(self, limit_per_source: int) -> int:
        inserted = 0
        for source in self.sources:
            try:
                for joke in source.fetch(limit_per_source):
                    if self.db.insert_joke(joke):
                        inserted += 1
            except Exception:
                logger.exception("Failed to ingest jokes from source: %s", source.name)
        return inserted
