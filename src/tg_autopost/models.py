from dataclasses import dataclass
from datetime import datetime


@dataclass
class Joke:
    text: str
    source_name: str
    source_url: str
    external_id: str
    content_hash: str
    source_views: int = 0
    created_at: datetime | None = None
    published_at: datetime | None = None
